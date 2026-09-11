"""Seed one audited Xiaomi acceptance from retained, independently checked evidence."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from data_provider.tencent_fetcher import TencentFetcher, _extract_kline_rows
from src.core.trading_calendar import get_effective_trading_date
from src.services.intelligence_service import IntelligenceService
from src.services.market_data_integrity import validate_daily_context
from src.storage import get_db


def prepare():
    root = Path('probe')
    read = lambda name: json.loads((root / (name + '.json')).read_text())
    history = read('openbb_history')
    tencent = read('tencent_history')
    now = datetime.now(timezone.utc)
    for evidence in (history, tencent):
        age = now - datetime.fromisoformat(evidence['retrieved_at'])
        if not timedelta(0) <= age <= timedelta(hours=24):
            raise ValueError('Source snapshot exceeds the one-day acceptance validity window')
    target = str(get_effective_trading_date('hk'))
    yahoo = pd.DataFrame(history['result']).sort_values('date')
    raw = pd.DataFrame(_extract_kline_rows(tencent['result']['body'], symbol='hk01810'))
    fetcher = TencentFetcher()
    df = fetcher._calculate_indicators(fetcher._clean_data(fetcher._normalize_data(raw, 'HK01810')))
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    df = df[df['date'] <= target].sort_values('date')
    if len(df) < 60 or yahoo.iloc[-1]['date'] != target or df.iloc[-1]['date'] != target:
        raise ValueError('Incomplete latest session/history coverage')
    overlap = df.merge(yahoo, on='date', suffixes=('_tencent','_yahoo'))
    if len(overlap) < 60:
        raise ValueError('Insufficient independent overlap')
    for field in ('open', 'high', 'low', 'close', 'volume'):
        tolerance = 0 if field == 'volume' else 0.005
        if ((overlap[field+'_tencent'] - overlap[field+'_yahoo']).abs() > tolerance).any():
            raise ValueError('Independent source disagreement: ' + field)
    today, yesterday = df.iloc[-1].to_dict(), df.iloc[-2].to_dict()
    validate_daily_context({'today':today, 'yesterday':yesterday}, target)
    reviewed = json.loads(Path('docs/xiaomi-reviewed-news.json').read_text())
    available_ids = {item['id'] for item in read('openbb_news')['result']}
    items = []
    for item in reviewed:
        published = datetime.fromisoformat(item['published_at'])
        if item['openbb_id'] not in available_ids or not timedelta(0) <= now-published <= timedelta(days=3):
            raise ValueError('Reviewed news missing from discovery or outside news window')
        items.append(dict(source_id=None, source_name='OpenBB news / reviewed sources',
                          source_type='manual', scope_type='symbol', scope_value='HK01810', market='hk',
                          title=item['title'], summary=item['summary'], url=item['url'], source=item['source'],
                          published_at=published.astimezone(timezone.utc).replace(tzinfo=None),
                          fetched_at=now.replace(tzinfo=None), raw_payload=json.dumps(item, ensure_ascii=False)))
    if len(items) < 2:
        raise ValueError('Insufficient reviewed company evidence')
    get_db().save_daily_data(df, 'HK01810', 'TencentFetcher / OpenBB-Yahoo cross-checked')
    IntelligenceService().repo.upsert_items(items)
    audit = dict(target=target, overlap=len(overlap), today=today, yesterday=yesterday,
                 reviewed_news_count=len(items), source_snapshots='Actions source audit artifact',
                 limitation='News uses reviewed public excerpts/summaries; full article retrieval unavailable. Not exhaustive issuer disclosure coverage.')
    (root/'preflight.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,default=str))
    print('PREFLIGHT',json.dumps(audit,ensure_ascii=False,default=str))


if __name__ == '__main__':
    prepare()
