"""Regression checks against observed HK field layout, distinct from A shares."""
from unittest.mock import Mock, patch

import pytest

from data_provider.tencent_fetcher import TencentFetcher, _to_tencent_symbol


@pytest.mark.parametrize('code', ['hk01810', 'HK01810', '1810.HK', '01810.HK'])
def test_hk_symbol(code):
    assert _to_tencent_symbol(code) == 'hk01810'


def test_hk_daily_endpoint_units_and_corporate_action_field():
    response = Mock()
    response.json.return_value = {'data': {'hk01810': {'day': [
        ['2026-09-10', '26.04', '25.92', '26.4', '25.68', '148663013', {'cqr':'2026-09-10'}, '0.7', '385095.02'],
        ['2026-09-11', '25.66', '26.36', '26.66', '25.44', '113533443', {}, '0.53', '296955.29'],
    ]}}}
    with patch('data_provider.tencent_fetcher.requests.get', return_value=response) as get:
        data = TencentFetcher().get_daily_data('hk01810', '2026-09-10', '2026-09-11')
    assert 'hkfqkline' in get.call_args.args[0]
    last = data.iloc[-1]
    assert last['volume'] == 113533443
    assert last['amount'] == pytest.approx(2969552900)
    assert last['open'] == 25.66
    assert last['close'] == 26.36
    assert last['pct_chg'] == pytest.approx((26.36/25.92-1)*100)
