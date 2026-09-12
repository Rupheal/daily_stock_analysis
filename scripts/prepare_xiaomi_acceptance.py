"""Fresh independent prices and regional news before exposing a model key."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from data_provider.tencent_fetcher import TencentFetcher, _extract_kline_rows
from src.core.trading_calendar import get_effective_trading_date
from src.services.hk_company_news import approved_news_origin, refresh_company_news
from src.services.intelligence_service import IntelligenceService
from src.services.market_data_integrity import daily_consistency_facts, validate_daily_context
from src.storage import get_db


def compare_prices(primary, independent, target):
    """Require the same complete session, finite fields and 60 overlapping bars."""
    import numpy as np
    if len(primary) < 60 or independent.empty or primary.iloc[-1]['date'] != target or independent.iloc[-1]['date'] != target:
        raise ValueError('Incomplete latest session/history coverage')
    overlap = primary.merge(independent, on='date', suffixes=('_tencent', '_yahoo'), validate='one_to_one')
    if len(overlap) < 60:
        raise ValueError('Insufficient independent overlap')
    for field in ('open', 'high', 'low', 'close', 'volume'):
        left, right = overlap[field+'_tencent'], overlap[field+'_yahoo']
        if not np.isfinite(left).all() or not np.isfinite(right).all():
            raise ValueError('Missing independent values: ' + field)
        tolerance = 0 if field == 'volume' else 0.005
        if ((left-right).abs() > tolerance).any():
            raise ValueError('Independent source disagreement: ' + field)
    return len(overlap)


def prepare():
    root = Path('probe'); root.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
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
    overlap = compare_prices(df, yahoo, target)
    today, yesterday = df.iloc[-1].to_dict(), df.iloc[-2].to_dict()
    context = {'today': today, 'yesterday': yesterday,
               'volume_change_ratio': round(today['volume']/yesterday['volume'], 2)}
    validate_daily_context(context, target)
    service = IntelligenceService()
    news = refresh_company_news(service, 'hk01810', '小米集团-W', days=3)
    reviewed = json.loads(Path('docs/xiaomi-reviewed-news.json').read_text())
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
            title=item['title'], summary=item['summary'], url=item['url'], source=item['source'],
            published_at=published.astimezone(timezone.utc).replace(tzinfo=None),
            fetched_at=now.replace(tzinfo=None), raw_payload=json.dumps(item, ensure_ascii=False)))
    service.repo.upsert_items(reviewed_items)
    items = {row['url']: row for row in news['items']}
    items.update({row['url']: row for row in reviewed_items})
    origins = sorted({approved_news_origin(item) for item in items.values()})
    (root/'news.json').write_text(json.dumps({'items': list(items.values()), 'origins': origins,
        'diagnostics': news['diagnostics'], 'review_diagnostics': review_diagnostics},
        ensure_ascii=False, indent=2, default=str))
    if len(items) < 3 or len(origins) < 2:
        raise ValueError('Insufficient dated company evidence')
    get_db().save_daily_data(df, 'HK01810', 'TencentFetcher / Yahoo cross-checked')
    audit = dict(passed=True, prepared_at=datetime.now(timezone.utc).isoformat(), target=target,
        overlap=overlap, today=today, yesterday=yesterday, news_count=len(items), origins=origins,
        facts=daily_consistency_facts(context), allowed_news_urls=list(items),
        limitation='Public excerpts and attributed reports; full issuer disclosure and event deduplication are incomplete.')
    (root/'preflight.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str))
    print('PREFLIGHT', json.dumps(audit, ensure_ascii=False, default=str))


if __name__ == '__main__':
    prepare()
