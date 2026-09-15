from datetime import date
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from o_native_date_boundary_adapter import _as_date, _is_hk_code, patched_yahoo_target_boundary


def test_helpers_are_strict_for_hk_and_dates():
    assert _as_date('2026-09-15') == date(2026, 9, 15)
    assert _is_hk_code('hk01810')
    assert _is_hk_code('1810.HK')
    assert not _is_hk_code('AAPL')


def test_adapter_shifts_only_target_hk_end_and_enables_repair(monkeypatch):
    import yfinance as yf
    from data_provider.yfinance_fetcher import YfinanceFetcher

    calls = []
    sentinel = object()

    def fake_download(*args, **kwargs):
        calls.append(dict(kwargs))
        return sentinel

    def fake_original(self, stock_code, start_date, end_date):
        return yf.download(tickers='1810.HK', start=start_date, end=end_date, auto_adjust=True)

    monkeypatch.setattr(yf, 'download', fake_download)
    with patch.object(YfinanceFetcher, '_fetch_raw_data', fake_original):
        with patched_yahoo_target_boundary('2026-09-15') as applied:
            result = YfinanceFetcher()._fetch_raw_data('hk01810', '2026-01-01', '2026-09-15')
    assert result is sentinel
    assert calls[-1]['end'] == '2026-09-16'
    assert calls[-1]['repair'] is True
    assert applied['count'] == 1


def test_adapter_does_not_shift_non_target_or_non_hk(monkeypatch):
    import yfinance as yf
    from data_provider.yfinance_fetcher import YfinanceFetcher

    calls = []
    def fake_download(*args, **kwargs):
        calls.append(dict(kwargs)); return object()
    def fake_original(self, stock_code, start_date, end_date):
        return yf.download(tickers='X', start=start_date, end=end_date, auto_adjust=True)

    monkeypatch.setattr(yf, 'download', fake_download)
    with patch.object(YfinanceFetcher, '_fetch_raw_data', fake_original):
        with patched_yahoo_target_boundary('2026-09-15') as applied:
            YfinanceFetcher()._fetch_raw_data('AAPL', '2026-01-01', '2026-09-15')
            YfinanceFetcher()._fetch_raw_data('hk01810', '2026-01-01', '2026-09-14')
    assert calls[0]['end'] == '2026-09-15' and 'repair' not in calls[0]
    assert calls[1]['end'] == '2026-09-14' and 'repair' not in calls[1]
    assert applied['count'] == 0
