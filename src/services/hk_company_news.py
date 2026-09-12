"""Public HK company news. No account, scraping browser, or paid search required.

Publisher assertions remain reported claims, never independently verified facts.
Only explicit publication timestamps are admitted; page retrieval is not publication.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

# Publisher geography is not a claim about CDN/server or reader IP location.
_SYNDICATED_PUBLISHERS = {
    'aastocks': ('AASTOCKS', 'HK'), '阿思達克': ('AASTOCKS', 'HK'),
    'dow jones': ('Dow Jones', 'US'), '道琼斯': ('Dow Jones', 'US'),
    '道瓊斯': ('Dow Jones', 'US'), 'mt newswires': ('MT Newswires', 'US'),
    'reuters': ('Reuters', 'Europe/international'), '路透社': ('Reuters', 'Europe/international'),
    'financial times': ('FT', 'Europe'), 'bloomberg': ('Bloomberg', 'US'),
    'cnbc': ('CNBC', 'US'), 'south china morning post': ('SCMP', 'HK'),
}
_DIRECT_PUBLISHERS = {
    'www.etnet.com.hk': ('ETNet', 'HK'), 'news.rthk.hk': ('RTHK', 'HK'),
    'www.ft.com': ('FT', 'Europe'), 'www.reuters.com': ('Reuters', 'Europe/international'),
    'www.aastocks.com': ('AASTOCKS', 'HK'), 'www.hkej.com': ('HKEJ', 'HK'),
    'www.scmp.com': ('SCMP', 'HK'), 'www.wsj.com': ('Dow Jones', 'US'),
    'www.cnbc.com': ('CNBC', 'US'), 'www.bloomberg.com': ('Bloomberg', 'US'),
    'www.hkexnews.hk': ('HKEXnews', 'HK'),
    'www1.hkexnews.hk': ('HKEXnews', 'HK'),
}
_REGIONAL_FEEDS = (
    ('etnet_editor', 'https://www.etnet.com.hk/www/tc/news/rss.php?section=editor', '《經濟通》新聞'),
    ('etnet_special', 'https://www.etnet.com.hk/www/tc/news/rss.php?section=special', '《經濟通》新聞'),
    ('rthk', 'https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml', '香港電台'),
    ('ft_hong_kong', 'https://www.ft.com/hong-kong?format=rss', 'Financial Times'),
    ('ft_asia', 'https://www.ft.com/asia-pacific?format=rss', 'Financial Times'),
)


def approved_news_origin(item):
    """Allow reviewed HK/US/European media; keep social/unknown/PR out of facts.

    In particular, mainland articles do not become HK reporting through Futu.
    The same gate is used when consuming old database records.
    """
    try:
        host = (urlsplit(str(item.get('url') or '')).hostname or '').lower()
    except ValueError:
        return None
    if host == 'news.futunn.com':
        publisher = str(item.get('source') or '').strip().casefold()
        return _SYNDICATED_PUBLISHERS.get(publisher)
    return _DIRECT_PUBLISHERS.get(host)


def symbol_digits(code):
    value = str(code).upper().removeprefix('HK').removesuffix('.HK')
    if not value.isdigit() or len(value) > 5:
        raise ValueError('Expected HK stock symbol')
    return value.zfill(5)


def aliases_for(code, name):
    name = re.sub(r'[-－](?:SW|W|B|Ｗ)$', '', name, flags=re.I).strip()
    aliases = [name] if len(name) >= 2 else []
    if symbol_digits(code) == '01810':
        aliases += ['小米', 'Xiaomi', 'Redmi']
    return aliases


def related(title, summary, code, name):
    text = title + ' ' + summary
    digits = symbol_digits(code)
    return any(alias.casefold() in text.casefold() for alias in aliases_for(code, name)) or bool(
        re.search(r'(?<!\d)' + digits + r'(?:\.HK|\b)', text, re.I))


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        raise ValueError('Missing public article URL')
    # Tracking parameters are removed only on these observed article URL formats.
    if parts.hostname in ('news.futunn.com', 'finance.sina.com.cn'):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    if parts.hostname == 'www.etnet.com.hk' and parts.path.endswith('quote_news_detail.php'):
        query = parse_qs(parts.query)
        if query.get('newsid'):
            return urlunsplit((parts.scheme, parts.netloc, parts.path,
                              urlencode({'newsid': query['newsid'][0]}), ''))
    return url


def select_company_evidence(items, limit, *, require_approved_origin=False, code=None, name=None):
    """Prioritize dated financial/risk coverage over consumer tutorials and PR.

    Ranking is a transparent relevance heuristic, not verification or sentiment.
    """
    ranked = []
    for item in items:
        if require_approved_origin and not approved_news_origin(item):
            continue
        if code and not related(str(item.get('title') or ''), '', code, name or ''):
            continue  # Body-only mentions belong to industry context, not core company evidence.
        title = str(item.get('title') or '')
        if re.search(r'如何.*(?:键盘|设置|安装)|使用教程|壁纸下载|铃声下载', title):
            continue
        priority = 0
        if re.search(r'调查|調查|监管|監管|诉讼|訴訟|印度|财报|財報|业绩|業績|盈利|回购|回購|资金|資金|净买入|淨買入|公告|评级|評級|earnings|profit|investigation|buyback|rating', title, re.I):
            priority = 2
        elif re.search(r'交付|订单|訂單|发布|發布|开源|開源|供应|供應|ETF', title):
            priority = 1
        ranked.append((priority, str(item.get('published_at') or ''), item))
    ranked.sort(key=lambda row:(row[0], row[1]), reverse=True)
    from src.services.hk_report_contract import event_identity
    selected, seen = [], set()
    for _, _, item in ranked:
        identity = event_identity(item)[0] if item.get('url') else None
        if identity is not None and identity in seen:
            continue
        seen.add(identity)
        selected.append(item)
    return selected[:limit]


def make_item(title, summary, url, published, source, channel, code, name, now, days):
    if published.tzinfo is None:
        raise ValueError('Publication timezone required')
    published = published.astimezone(timezone.utc)
    if not now - timedelta(days=days) <= published <= now:
        return None
    if not related(title, summary, code, name):
        return None
    kind = '观点/预测' if re.search(r'评级|評級|研报|研報|《大行》|券商精點|预期|預期|预计|預計|预测|預測|料收入|解盘|解盤|forecast|rating|price target', title, re.I) else '媒体报道（待原始披露复核）'
    return dict(source_id=None, source_name=channel, source_type='public_web',
                source=source, scope_type='symbol', scope_value='HK'+symbol_digits(code), market='hk',
                title=title, summary=f'[{kind}；公开摘要，非全文核验] {summary[:600]}',
                url=canonical_url(url), published_at=published.replace(tzinfo=None),
                fetched_at=now.replace(tzinfo=None), raw_payload=json.dumps({
                    'channel':channel, 'publisher':source, 'evidence_kind':kind,
                    'event_date':None, 'full_text_verified':False,
                    'company_match':'title_or_summary', 'independent_confirmation':False}, ensure_ascii=False))


def parse_futu(content, code, name, now, days=3):
    soup = BeautifulSoup(content, 'html.parser')
    script = next((x.get_text() for x in soup.find_all('script')
                   if x.get_text().strip().startswith('window.__INITIAL_STATE__=')), None)
    if not script:
        raise ValueError('Futu public news state missing')
    state = json.JSONDecoder().raw_decode(script.split('=', 1)[1].lstrip())[0]
    if str(state.get('stock_info', {}).get('stockCode')) != symbol_digits(code):
        raise ValueError('Futu page company mismatch')
    rows = state.get('stock_news', {}).get('list')
    if not isinstance(rows, list):
        raise ValueError('Futu public news schema changed')
    items = []
    for row in rows:
        try:
            published = datetime.fromtimestamp(float(row['time']), timezone.utc)
            item = make_item(row['title'], row.get('abstract') or '', row['url'], published,
                             row.get('source') or '富途资讯', '富途公开新闻', code, name, now, days)
            if item: items.append(item)
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return items


def sina_candidates(content, code, name):
    soup = BeautifulSoup(content, 'html.parser')
    urls = []
    for a in soup.select('a[href]'):
        url = a['href']
        title = a.get('title') or a.get_text(' ', strip=True)
        if (urlsplit(url).hostname == 'finance.sina.com.cn' and '/doc-' in url
                and related(title, '', code, name) and url not in urls):
            urls.append(url)
    return urls[:6]


def parse_sina_article(content, url, code, name, now, days=3):
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.select_one('h1.main-title, h1')
    timestamp = soup.select_one('.date-source .date, #pub_date')
    if not heading or not timestamp:
        return None
    match = re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', timestamp.get_text(' ', strip=True))
    if not match:
        return None
    published = datetime(*map(int, match.groups()), tzinfo=ZoneInfo('Asia/Shanghai'))
    article = soup.select_one('#artibody, .article')
    summary = article.get_text(' ', strip=True)[:600] if article else ''
    source = soup.select_one('.date-source .source')
    return make_item(heading.get_text(' ', strip=True), summary, url, published,
                     source.get_text(' ', strip=True) if source else '新浪财经',
                     '新浪财经公开新闻', code, name, now, days)


def etnet_candidates(content, code, name, now, days=3):
    """Use each story's own full date, never the quote/page update timestamp."""
    soup = BeautifulSoup(content, 'html.parser')
    candidates = {}
    base = 'https://www.etnet.com.hk/www/tc/stocks/realtime/'
    for block in soup.select('.DivArticleList'):
        stamp = block.select_one('.date')
        if not stamp:
            continue
        try:
            published = datetime.strptime(stamp.get_text(strip=True), '%d/%m/%Y %H:%M').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
        except ValueError:
            continue
        if not now - timedelta(days=days) <= published <= now:
            continue
        for link in block.select('a[href]'):
            url = urljoin(base, link['href'])
            parts = urlsplit(url)
            query = parse_qs(parts.query)
            if (parts.hostname != 'www.etnet.com.hk' or not parts.path.endswith('/quote_news_detail.php')
                    or query.get('code') != [str(int(symbol_digits(code)))]) or not related(link.get_text(), '', code, name):
                continue
            newsid = query.get('newsid', [''])[0]
            if newsid and newsid not in candidates:
                candidates[newsid] = (published, url)
    return [row[1] for row in sorted(candidates.values(), reverse=True)[:6]]


def parse_etnet_article(content, url, code, name, now, days=3):
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.select_one('h1.ArticleHdr')
    block = heading.find_parent(class_='DivArticleList') if heading else None
    stamp = block.select_one('.date') if block else None
    body = soup.select_one('#NewsContent [itemprop="articleBody"]')
    if not heading or not stamp or not body:
        return None
    try:
        published = datetime.strptime(stamp.get_text(strip=True), '%d/%m/%Y %H:%M').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
    except ValueError:
        return None
    return make_item(heading.get_text(' ', strip=True), body.get_text(' ', strip=True), url,
                     published, '《經濟通》新聞', '經濟通公開公司新聞', code, name, now, days)


def parse_regional_rss(content, source, code, name, now, days=3):
    """RSS excerpts with explicit timezone and original publisher links only."""
    root = ET.fromstring(content)
    if root.tag != 'rss':
        raise ValueError('Regional source did not return RSS')
    items = []
    for node in root.findall('./channel/item')[:50]:
        try:
            published = parsedate_to_datetime(node.findtext('pubDate') or '')
            title = node.findtext('title') or ''
            summary = BeautifulSoup(node.findtext('description') or '', 'html.parser').get_text(' ', strip=True)
            item = make_item(title, summary, node.findtext('link') or '', published,
                             source, source + ' RSS', code, name, now, days)
            if item and approved_news_origin(item):
                items.append(item)
        except (ValueError, TypeError, OverflowError):
            continue
    return items


def fetch_public(service, url):
    """Reuse native SSRF/DNS and size protections. Redirects fail closed."""
    service._validate_url(url)
    response = service._get_with_validated_dns(url, timeout=(8, 15),
        headers={'User-Agent':'Mozilla/5.0'}, allow_redirects=False, stream=True)
    try:
        if response.status_code != 200:
            raise ValueError(f'Public news HTTP {response.status_code}')
        content = service._read_limited_response(response)
        # Sina stock pages use legacy Chinese encoding; article/Futu pages use UTF-8.
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('gb18030')
    finally:
        response.close()


def refresh_company_news(service, code, name, days=3, now=None):
    now = now or datetime.now(timezone.utc)
    code = symbol_digits(code)
    items, diagnostics = [], []
    for channel in ('etnet_company', 'futu') + tuple(row[0] for row in _REGIONAL_FEEDS):
        try:
            if channel == 'futu':
                html = fetch_public(service, f'https://www.futunn.com/stock/{code}-HK/news')
                rows = parse_futu(html, code, name, now, days)
            elif channel == 'etnet_company':
                html = fetch_public(service, 'https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news.php?' + urlencode({'code':int(code)}))
                rows = []
                for url in etnet_candidates(html, code, name, now, days):
                    try:
                        item = parse_etnet_article(fetch_public(service, url), url, code, name, now, days)
                        if item: rows.append(item)
                    except Exception as exc:
                        diagnostics.append({'source':'etnet_article', 'url':url, 'error':type(exc).__name__})
            else:
                _, url, publisher = next(row for row in _REGIONAL_FEEDS if row[0] == channel)
                rows = parse_regional_rss(fetch_public(service, url), publisher, code, name, now, days)
            before_filter = len(rows)
            rows = [row for row in rows if approved_news_origin(row)]
            for row in rows:
                family, region = approved_news_origin(row)
                payload = json.loads(row['raw_payload'])
                payload.update(publisher_family=family, publisher_region=region, source_policy='hk-us-europe', server_region_verified=False)
                row['raw_payload'] = json.dumps(payload, ensure_ascii=False)
            items.extend(rows)
            diagnostics.append({'source':channel, 'accepted':len(rows), 'excluded_origin':before_filter-len(rows)})
        except Exception as exc:
            diagnostics.append({'source':channel, 'error':type(exc).__name__, 'detail':str(exc)[:200]})
    seen_urls, seen_titles, unique = set(), set(), []
    for item in sorted(items, key=lambda x:x['published_at'], reverse=True):
        title = re.sub(r'\W+', '', item['title']).casefold()
        if item['url'] in seen_urls or title in seen_titles:
            continue
        seen_urls.add(item['url']); seen_titles.add(title); unique.append(item)
    saved = service.repo.upsert_items(unique)
    return {'accepted':len(unique), 'saved':saved, 'diagnostics':diagnostics,
            'items':unique, 'event_deduplication':'URL and normalized title only; related reports are not independent confirmation'}
