"""Public HK company news. No account, scraping browser, or paid search required.

Publisher assertions remain reported claims, never independently verified facts.
Only explicit publication timestamps are admitted; page retrieval is not publication.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


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
    return url


def make_item(title, summary, url, published, source, channel, code, name, now, days):
    if published.tzinfo is None:
        raise ValueError('Publication timezone required')
    published = published.astimezone(timezone.utc)
    if not now - timedelta(days=days) <= published <= now:
        return None
    if not related(title, summary, code, name):
        return None
    kind = '观点/预测' if re.search(r'评级|研报|《大行》|预期|预计|预测|料收入|解盘', title) else '媒体报道（待原始披露复核）'
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
    for channel in ('futu', 'sina'):
        try:
            if channel == 'futu':
                html = fetch_public(service, f'https://www.futunn.com/stock/{code}-HK/news')
                rows = parse_futu(html, code, name, now, days)
            else:
                html = fetch_public(service, f'https://stock.finance.sina.com.cn/hkstock/quotes/{code}.html')
                rows = []
                for url in sina_candidates(html, code, name):
                    try:
                        item = parse_sina_article(fetch_public(service, url), url, code, name, now, days)
                        if item: rows.append(item)
                    except Exception as exc:
                        diagnostics.append({'source':'sina_article', 'url':url, 'error':type(exc).__name__})
            items.extend(rows)
            diagnostics.append({'source':channel, 'accepted':len(rows)})
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
