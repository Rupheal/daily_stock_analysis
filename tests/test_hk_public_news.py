import json
from datetime import datetime, timezone
from types import SimpleNamespace

from src.services.hk_company_news import parse_futu, parse_sina_article
from src.services.market_data_integrity import enforce_daily_report

NOW = datetime(2026, 9, 11, 20, 30, tzinfo=timezone.utc)


def test_news_rejects_wrong_company_old_future_missing_time_and_dedicated_page_noise():
    valid = dict(title='小米发布公告', abstract='报道摘要', time=1789113161,
                 url='https://news.futunn.com/post/123?tracking=1', source='财联社')
    rows = [valid, dict(valid, title='其他公司公告'), dict(valid, time=1),
            dict(valid, time=NOW.timestamp()+10), dict(valid, time=None)]
    html = '<script>window.__INITIAL_STATE__='+json.dumps({
        'stock_info':{'stockCode':'01810'}, 'stock_news':{'list':rows}})+'</script>'
    items = parse_futu(html, 'hk01810', '小米集团-W', NOW)
    assert len(items) == 1
    assert items[0]['url'] == 'https://news.futunn.com/post/123'
    assert items[0]['published_at'].tzinfo is None  # repository UTC convention
    assert not json.loads(items[0]['raw_payload'])['independent_confirmation']
    import pytest
    with pytest.raises(ValueError, match='company mismatch'):
        parse_futu(html, 'hk00700', '腾讯控股', NOW)


def test_sina_requires_explicit_article_timestamp_and_labels_opinion():
    html = '<h1>小米评级研报</h1><div class="date-source"><span class="date">2026年09月11日 15:52</span></div><div id="artibody">分析师预计增长</div>'
    item = parse_sina_article(html, 'https://finance.sina.com.cn/a.shtml', 'hk01810', '小米集团', NOW)
    assert item['published_at'] == datetime(2026, 9, 11, 7, 52)
    assert '观点/预测' in item['summary']
    assert parse_sina_article('<h1>小米公告</h1>', item['url'], 'hk01810', '小米集团', NOW) is None


def test_output_gate_removes_execution_plan_on_observed_error():
    row = {'pattern_analysis':'实体较小', 'dashboard':{'battle_plan':{'buy':'now'}}}
    result = SimpleNamespace(success=True, dashboard=row['dashboard'], to_dict=lambda:row)
    audit = enforce_daily_report(result, {'today':dict(open=25.66,high=26.66,low=25.44,close=26.36)})
    assert not audit['passed']
    assert not result.success
    assert result.dashboard is None


def test_hk_route_prefers_tencent_and_falls_back_when_daily_is_stale():
    from unittest.mock import Mock
    import pandas as pd
    from data_provider.base import DataFetcherManager
    manager = DataFetcherManager.__new__(DataFetcherManager)
    fetchers = [SimpleNamespace(name=name) for name in ('YfinanceFetcher', 'AkshareFetcher', 'TencentFetcher')]
    manager._get_fetchers_snapshot = lambda: fetchers
    manager._warn_bare_index_conflict = lambda target: None
    manager._filter_daily_fetchers_for_market = lambda items, market: items
    manager._filter_fetchers_by_capability = lambda items, **kwargs: items
    manager._is_daily_source_available = lambda *args: True
    manager._record_daily_source_success = lambda *args: None
    manager._record_daily_source_failure = lambda *args: None
    calls = []
    def fetch(provider, *args, **kwargs):
        calls.append(provider.name)
        return pd.DataFrame([{'date':'2026-09-10' if provider.name == 'TencentFetcher' else '2026-09-11'}])
    manager._call_fetcher_method = fetch
    frame, provider = manager.get_daily_data('hk01810', end_date='2026-09-11')
    assert provider == 'AkshareFetcher'
    assert calls == ['TencentFetcher', 'AkshareFetcher']
