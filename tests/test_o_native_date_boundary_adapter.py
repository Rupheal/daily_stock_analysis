from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from o_native_date_boundary_adapter import (
    _as_date,
    _is_hk_code,
    _is_hk_ticker_request,
    patched_yahoo_target_boundary,
)


def test_helpers_are_strict_for_hk_and_dates():
    assert _as_date('2026-09-15') == date(2026, 9, 15)
    assert _is_hk_code('hk01810')
    assert _is_hk_code('1810.HK')
    assert not _is_hk_code('AAPL')
    assert _is_hk_ticker_request((), {'tickers': '1810.HK'})
    assert _is_hk_ticker_request(('0700.HK',), {})
    assert not _is_hk_ticker_request((), {'tickers': 'AAPL'})


def test_adapter_shifts_only_target_hk_end_and_enables_repair(monkeypatch):
    import yfinance as yf

    calls = []
    sentinel = object()

    def fake_download(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(yf, 'download', fake_download)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        result = yf.download(tickers='1810.HK', start='2026-01-01', end='2026-09-15', auto_adjust=True)
    assert result is sentinel
    assert calls[-1][1]['end'] == '2026-09-16'
    assert calls[-1][1]['repair'] is True
    assert applied['count'] == 1


def test_adapter_does_not_shift_non_target_or_non_hk(monkeypatch):
    import yfinance as yf

    calls = []
    def fake_download(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return object()

    monkeypatch.setattr(yf, 'download', fake_download)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        yf.download(tickers='AAPL', start='2026-01-01', end='2026-09-15', auto_adjust=True)
        yf.download(tickers='1810.HK', start='2026-01-01', end='2026-09-14', auto_adjust=True)
    assert calls[0][1]['end'] == '2026-09-15' and 'repair' not in calls[0][1]
    assert calls[1][1]['end'] == '2026-09-14' and 'repair' not in calls[1][1]
    assert applied['count'] == 0
