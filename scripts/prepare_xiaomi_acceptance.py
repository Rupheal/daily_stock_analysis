"""Fresh independent prices and regional news before exposing a model key."""
import json
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from data_provider.tencent_fetcher import TencentFetcher, _extract_kline_rows
from src.core.trading_calendar import get_effective_trading_date
from src.services.hk_company_news import approved_news_origin, refresh_company_news, canonical_url, related
from src.services.intelligence_service import IntelligenceService
from src.services.market_data_integrity import daily_consistency_facts, validate_daily_context
from src.services.hk_report_contract import attach_report_contract, deduplicate_events
from src.services.hk_volume_reconciliation import (
    reconcile_volume_pairs,
    validate_latest_session,
    validate_ohlc_pairs,
)
from src.storage import get_db

REPO_ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def fetch_issuer_announcements(now, root):
    """Discoverable public feed embedded by ir.mi.com; dates retain day precision.

    Euroland's displayed dates and raw epoch fields have ambiguous timezone
    semantics. Do not turn either into a fabricated exact publication time.
    """
    from urllib.parse import quote
    response = requests.get('https://ir.mi.com/news-events/announcements', timeout=20)
    response.raise_for_status()
    if 'asia.tools.euroland.com/tools/pressreleases/' not in response.text:
        raise ValueError('Issuer feed delegation no longer verifiable')
    endpoint = 'https://asia.tools.euroland.com/tools/Pressreleases/Main/GetNews/'
    response = requests.post(endpoint, data={'companyCode': 'ky-1810', 'lang': 'en-GB',
        'strYears': str(now.year), 'pageIndex': '0', 'pageJummp': '50', 'orderBy': '0',
        'strDateFrom': (now-timedelta(days=7)).strftime('%d/%m/%Y'),
        'strDateTo': now.strftime('%d/%m/%Y'), 'typeFilter': '', 'searchPhrase': '', 'v': '',
        'hasTypeFilter': 'false', 'onlyInsiderInfo': 'false', 'alwaysIncludeInsiders': 'false'}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    atomic_json(root/'issuer-feed-raw.json', payload)
    rows = payload.get('News')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Issuer announcement listing missing')
    items = []
    for row in rows:
        day = datetime.strptime(row['formatedDate'], '%b %d, %Y').date()
        if day > now.date():
            raise ValueError('Future issuer disclosure date')
        if day < (now-timedelta(days=7)).date():
            continue
        attachments = [a for a in payload.get('Attachments', []) if a['prID'] == row['ID']]
        urls = ['https://ea-cdn.eurolandir.com/press-releases-attachments/' + str(a['atID']) + '/' + quote(a['filename'])
                for a in attachments if a.get('mime') == 'application/pdf']
        if not urls:
            raise ValueError('Recent issuer announcement has no original attachment')
        items.append({'id': 'xiaomi-disclosure-' + str(row['ID']), 'title': row['title'],
            'published_date': day.isoformat(), 'publication_precision': 'day',
            'source_urls': urls, 'full_text_verified': False,
            'kind': '公司公告目录；正文尚未自动核验，不能推断回购数量或不存在其他风险'})
    result = {'retrieved_at': now.isoformat(), 'issuer_page': 'https://ir.mi.com/news-events/announcements',
        'feed_url': endpoint, 'items': items, 'listed_rows': len(rows), 'provider_total': payload.get('total'),
        'coverage_complete': False, 'timezone_note': '仅使用公告显示日期，原始epoch时区语义未确认。'}
    if not items:
        raise ValueError('No recent issuer announcement listing to inspect')
    atomic_json(root/'issuer-announcements.json', result)
    return result


def compare_prices(primary, independent, target, return_diagnostics=False):
    """Require same session, strict OHLC, exact history volume and calibrated latest volume.

    Historical volume remains exact-only. The latest session alone may use the
    evidence-bounded provider reconciliation rule calibrated in Actions Run
    34983641578; the calibration added no discretionary margin.
    """
    if len(primary) < 60 or independent.empty:
        raise ValueError('Incomplete latest session/history coverage')
    validate_latest_session(primary.iloc[-1]['date'], independent.iloc[-1]['date'], target)
    overlap = primary.merge(independent, on='date', suffixes=('_tencent', '_yahoo'), validate='one_to_one')
    if len(overlap) < 60:
        raise ValueError('Insufficient independent overlap')

    for field in ('open', 'high', 'low', 'close'):
        validate_ohlc_pairs(
            (field, left, right)
            for left, right in zip(overlap[field+'_tencent'], overlap[field+'_yahoo'])
        )

    corporate_action_dates = set()
    for action_field in ('stock splits', 'dividends', 'capital gains'):
        if action_field not in overlap.columns:
            continue
        values = pd.to_numeric(overlap[action_field], errors='coerce').fillna(0.0)
        corporate_action_dates.update(overlap.loc[values != 0.0, 'date'].astype(str).tolist())

    volume_diagnostics = reconcile_volume_pairs(
        zip(overlap['date'], overlap['volume_tencent'], overlap['volume_yahoo']),
        target,
        corporate_action_dates=corporate_action_dates,
        unit_semantics_verified=True,
    )
    diagnostics = {
        'overlap_sessions': len(overlap),
        'ohlc_absolute_tolerance': 0.005,
        'volume_rule': 'historical_exact_latest_calibrated_bound',
        'corporate_action_sessions_in_overlap': len(corporate_action_dates),
        'volume': volume_diagnostics,
    }
    if return_diagnostics:
        return len(overlap), diagnostics
    return len(overlap)


def prepare(root=None, allow_partial_news=False, include_primary_evidence=False):
    """Reuse the same price gate; facts-only callers may disclose news gaps.

    Paths needed by the acceptance workflow are repository-relative so the same
    gate behaves identically whether the repository is checked out at the runner
    root or under a subdirectory such as ``research/``.
    """
    root = REPO_ROOT/'probe' if root is None else Path(root)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    checkpoint = {'run_id': os.getenv('GITHUB_RUN_ID', now.strftime('%Y%m%dT%H%M%SZ')),
        'commit': os.getenv('GITHUB_SHA'), 'started_at': now.isoformat(), 'model_http_requests': 0,
        'tasks': {key: 'pending' for key in ('prices', 'news', 'issuer', 'manifest')}}
    atomic_json(root/'acceptance-queue.json', checkpoint)
    target = str(get_effective_trading_date('hk'))
    endpoint = 'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get'
    response = requests.get(endpoint, params={'param': 'hk01810,day,,,180,qfq'}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    (root/'tencent_history.json').write_text(json.dumps({'retrieved_at': now.isoformat(),
        'url': response.url, 'adjustment': 'qfq', 'result': payload}, ensure_ascii=False))
    raw = pd.DataFrame(_extract_kline_rows(payload, symbol='hk01810'))
    fetcher = TencentFetcher()
    df = fetcher._calculate_indicators(fetcher._clean_data(fetcher._normalize_data(raw, 'HK01810')))
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    df = df[df['date'] <= target].sort_values('date')
    # Same Yahoo provider previously tested through OpenBB, using the DSA dependency.
    history = yf.Ticker('1810.HK').history(period='6mo', auto_adjust=True, actions=True, timeout=20)
    if history.empty:
        raise ValueError('Yahoo independent history unavailable; no model call allowed')
    yahoo = history.reset_index()
    yahoo.columns = [str(c).lower() for c in yahoo.columns]
    yahoo['date'] = pd.to_datetime(yahoo['date']).dt.strftime('%Y-%m-%d')
    yahoo = yahoo[yahoo['date'] <= target].sort_values('date')
    (root/'independent_history.json').write_text(json.dumps({'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'provider': 'Yahoo via yfinance', 'adjustment': 'auto_adjust=True (splits/dividends)',
        'result': yahoo.to_dict('records')}, ensure_ascii=False, default=str))
    overlap, price_reconciliation = compare_prices(df, yahoo, target, return_diagnostics=True)
    today, yesterday = df.iloc[-1].to_dict(), df.iloc[-2].to_dict()
    context = {'today': today, 'yesterday': yesterday,
               'volume_change_ratio': round(today['volume']/yesterday['volume'], 2)}
    validate_daily_context(context, target)
    checkpoint['tasks']['prices'] = 'passed'
    atomic_json(root/'acceptance-queue.json', checkpoint)
    try:
        service = IntelligenceService()
        news = refresh_company_news(service, 'hk01810', '小米集团-W', days=3)
        reviewed = json.loads((REPO_ROOT/'docs/xiaomi-reviewed-news.json').read_text())
        reviewed_items, review_diagnostics = [], []
        for item in reviewed:
            published = datetime.fromisoformat(item['published_at'])
            if published.tzinfo is None or not timedelta(0) <= now-published <= timedelta(days=3):
                review_diagnostics.append({'url': item['url'], 'status': 'outside_current_window'})
                continue
            if not approved_news_origin(item):
                raise ValueError('Reviewed news violates regional source policy')
            reviewed_items.append(dict(source_id=None, source_name='Reviewed regional evidence',
                source_type='public_web', scope_type='symbol', scope_value='HK01810', market='hk',
                title=item['title'], summary=item['summary'], url=canonical_url(item['url']), source=item['source'],
                published_at=published.astimezone(timezone.utc).replace(tzinfo=None),
                fetched_at=now.replace(tzinfo=None), raw_payload=json.dumps(item, ensure_ascii=False)))
        service.repo.upsert_items(reviewed_items)
        all_items = news['items']
        industry_context = [row for row in all_items if not related(row['title'], '', 'HK01810', '小米集团-W')]
        items = {canonical_url(row['url']): row for row in all_items
                 if related(row['title'], '', 'HK01810', '小米集团-W')}
        items.update({row['url']: row for row in reviewed_items})
        origins = sorted({approved_news_origin(item) for item in items.values()})
        (root/'news.json').write_text(json.dumps({'items': list(items.values()), 'origins': origins,
            'diagnostics': news['diagnostics'], 'review_diagnostics': review_diagnostics,
            'industry_context_items': industry_context, 'fetched_company_mentions': len(all_items)},
            ensure_ascii=False, indent=2, default=str))
        if (len(items) < 3 or len(origins) < 2) and not allow_partial_news:
            raise ValueError('Insufficient dated company evidence')
        events = deduplicate_events(list(items.values()))
        context['company_news_evidence'] = [{'event_id': e['event_id'], 'title': e['title'],
            'summary': e['summary'], 'source': e['source'], 'published_at': str(e['published_at']),
            'source_urls': e['event_source_urls'],
            'source_records': e['event_source_records'],
            'evidence_kind': (json.loads(e.get('raw_payload') or '{}').get('evidence_kind')
                              or '媒体报道；待原始披露核验')} for e in events]
    except Exception as exc:
        if not allow_partial_news:
            raise
        items, origins, events, industry_context = {}, [], [], []
        context['company_news_evidence'] = []
        atomic_json(root/'news.json', {'items': [], 'origins': [], 'status': 'failed',
            'diagnostics': [{'stage': 'company_news', 'status': 'failed',
                             'error': type(exc).__name__ + ': ' + str(exc)}]})
    checkpoint['tasks']['news'] = 'passed_limited_coverage' if items else 'unavailable'
    atomic_json(root/'acceptance-queue.json', checkpoint)
    try:
        issuer = fetch_issuer_announcements(now, root)
        checkpoint['tasks']['issuer'] = 'listing_passed_body_incomplete'
    except Exception as exc:
        if not allow_partial_news:
            raise
        issuer = {'items': [], 'coverage_complete': False,
                  'status': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)}
        atomic_json(root/'issuer-announcements.json', issuer)
        checkpoint['tasks']['issuer'] = 'failed'
    atomic_json(root/'acceptance-queue.json', checkpoint)
    attach_report_contract(context, 'HK01810')
    primary_evidence = None
    if include_primary_evidence:
        from src.services.xiaomi_primary_evidence import collect_primary_evidence
        primary_evidence = collect_primary_evidence(root/'primary')
        atomic_json(root/'primary-evidence.json', primary_evidence)
        checkpoint['tasks']['primary_evidence'] = 'passed' if primary_evidence['passed'] else 'incomplete'
    atomic_json(root/'reviewed-evidence.json', context['hk_report_contract'])
    get_db().save_daily_data(df, 'HK01810', 'TencentFetcher / Yahoo cross-checked')
    audit = dict(passed=True, symbol='HK01810', prices_passed=True,
        component_status=dict(checkpoint['tasks']),
        news_diagnostics=json.loads((root/'news.json').read_text()).get('diagnostics', []),
        prepared_at=datetime.now(timezone.utc).isoformat(), target=target,
        overlap=overlap, price_reconciliation=price_reconciliation,
        today=today, yesterday=yesterday, news_count=len(items), origins=origins,
        facts=daily_consistency_facts(context), allowed_news_urls=list(items),
        hk_report_contract=context['hk_report_contract'], issuer_announcements=issuer,
        event_candidates=len(events), reviewed_group_count=sum(e['grouping_reviewed'] for e in events),
        industry_context_count=len(industry_context), company_news_evidence=context['company_news_evidence'],
        limitation='Known event families merged; unknown events are upper-bound candidates. Issuer listing verified; full disclosure bodies and financial periods remain incomplete.')
    if primary_evidence is not None:
        audit['verified_primary_evidence'] = primary_evidence
        audit['limitation'] = 'Only reviewed primary fields are admitted separately; complete filings/news coverage and strategy validity remain unverified.'
    atomic_json(root/'preflight.json', audit)
    files = ['tencent_history.json', 'independent_history.json', 'news.json', 'issuer-feed-raw.json',
             'issuer-announcements.json', 'reviewed-evidence.json', 'preflight.json']
    if primary_evidence is not None:
        files.append('primary-evidence.json')
    manifest = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                for name in files if (root/name).is_file()}
    checkpoint.update(manifest=manifest, finished_at=datetime.now(timezone.utc).isoformat())
    checkpoint['tasks']['manifest'] = 'passed'
    atomic_json(root/'acceptance-queue.json', checkpoint)
    print('PREFLIGHT', json.dumps(audit, ensure_ascii=False, default=str))
    return audit


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-primary-evidence', action='store_true')
    prepare(include_primary_evidence=parser.parse_args().with_primary_evidence)
