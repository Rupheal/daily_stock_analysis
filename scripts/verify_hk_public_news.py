"""Live free-news ingestion and DSA context acceptance, with no model call."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.config import get_config
from src.services.intelligence_service import IntelligenceService
from src.services.hk_company_news import approved_news_origin, refresh_company_news
from src.core.pipeline import StockAnalysisPipeline


def main():
    config = get_config()
    service = IntelligenceService(config=config)
    result = refresh_company_news(service, 'hk01810', '小米集团-W', days=3)
    out = Path('probe/media-integration'); out.mkdir(parents=True, exist_ok=True)
    (out/'news.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print('NEWS_RESULT', json.dumps({k:v for k,v in result.items() if k != 'items'}, ensure_ascii=False))
    origins = sorted({approved_news_origin(item) for item in result['items'] if approved_news_origin(item)})
    print('NEWS_ORIGINS', json.dumps(origins, ensure_ascii=False))
    assert len(result['items']) >= 3 and len(origins) >= 2, 'Insufficient dated multi-publisher company evidence'
    assert all(approved_news_origin(item) for item in result['items'])
    # Confirm a pre-migration mainland record is not consumed from the database.
    old_item = dict(result['items'][0], title='小米 SOURCE_POLICY_SENTINEL',
                    source='财联社', url='https://news.futunn.com/post/source-policy-sentinel',
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None))
    service.repo.upsert_items([old_item])
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = config
    # Network fetch was performed above. Exercise the real DB consumer once.
    with patch.object(IntelligenceService, 'refresh_auto_sources', return_value={}), patch(
            'src.services.hk_company_news.refresh_company_news', return_value=result):
        context = pipeline._load_persisted_intelligence_context(
            code='hk01810', stock_name='小米集团-W', market='hk', limit=12)
    (out/'dsa-news-context.txt').write_text(context or '')
    print('DSA_CONTEXT', context)
    assert result['accepted'] > 0 and context and '来源：https://' in context
    assert '小米' in context
    assert 'SOURCE_POLICY_SENTINEL' not in context
    print('PASS: public news fetched, dated, matched, persisted and consumed by DSA; no LLM called')
    from data_provider.base import DataFetcherManager
    from src.core.trading_calendar import get_effective_trading_date
    target = get_effective_trading_date('hk')
    frame, provider = DataFetcherManager().get_daily_data('hk01810', end_date=str(target), days=100)
    daily = {'provider':provider, 'target_date':str(target), 'rows':len(frame),
             'latest':frame.tail(2).to_dict(orient='records')}
    (out/'daily.json').write_text(json.dumps(daily, ensure_ascii=False, indent=2, default=str))
    print('DAILY_RESULT', json.dumps(daily, ensure_ascii=False, default=str))
    assert provider == 'TencentFetcher' and str(frame['date'].max())[:10] == str(target)


if __name__ == '__main__':
    main()
