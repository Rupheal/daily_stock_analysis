from datetime import date, datetime
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
    assert _as_date('20260915') == date(2026, 9, 15)
    assert _as_date(datetime(2026, 9, 15, 12, 30)) == date(2026, 9, 15)
    assert _is_hk_code('hk01810')
    assert _is_hk_code('1810.HK')
    assert not _is_hk_code('AAPL')
    assert _is_hk_ticker_request((), {'tickers': '1810.HK'})
    assert _is_hk_ticker_request(('0700.HK',), {})
    assert not _is_hk_ticker_request((), {'tickers': 'AAPL'})


def test_adapter_shifts_target_hk_yahoo_end_and_enables_repair(monkeypatch):
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
    assert applied['yahoo_count'] == 1
    assert applied['akshare_count'] == 0
    assert applied['boundary_shift_count'] == 1
    assert applied['repair_enable_count'] == 1


def test_adapter_repairs_already_shifted_yahoo_target_plus_one_without_extending_again(monkeypatch):
    import yfinance as yf

    calls = []
    sentinel = object()

    def fake_download(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(yf, 'download', fake_download)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        result = yf.download(tickers='1810.HK', start='2026-01-01', end='2026-09-16', auto_adjust=True)
    assert result is sentinel
    assert calls[-1][1]['end'] == '2026-09-16'
    assert calls[-1][1]['repair'] is True
    assert applied['count'] == 1
    assert applied['yahoo_count'] == 1
    assert applied['boundary_shift_count'] == 0
    assert applied['repair_enable_count'] == 1


def test_adapter_caps_akshare_target_plus_one_keyword_end(monkeypatch):
    import akshare as ak

    calls = []
    sentinel = object()

    def fake_hk_hist(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(ak, 'stock_hk_hist', fake_hk_hist)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        result = ak.stock_hk_hist(symbol='01810', period='daily', start_date='20260718', end_date='20260916', adjust='qfq')
    assert result is sentinel
    assert calls[-1][1]['end_date'] == '20260915'
    assert applied['count'] == 1
    assert applied['akshare_count'] == 1
    assert applied['akshare_cap_count'] == 1
    assert applied['yahoo_count'] == 0


def test_adapter_caps_akshare_positional_end(monkeypatch):
    import akshare as ak

    calls = []
    sentinel = object()

    def fake_hk_hist(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(ak, 'stock_hk_hist', fake_hk_hist)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        result = ak.stock_hk_hist('01810', 'daily', '20260718', '20260916', 'qfq')
    assert result is sentinel
    assert calls[-1][0][3] == '20260915'
    assert applied['akshare_count'] == 1
    assert applied['akshare_cap_count'] == 1


def test_adapter_leaves_older_or_far_future_akshare_requests_unchanged(monkeypatch):
    import akshare as ak

    calls = []
    def fake_hk_hist(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return object()

    monkeypatch.setattr(ak, 'stock_hk_hist', fake_hk_hist)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        ak.stock_hk_hist(symbol='01810', period='daily', start_date='20260718', end_date='20260914', adjust='qfq')
        ak.stock_hk_hist(symbol='01810', period='daily', start_date='20260718', end_date='20260917', adjust='qfq')
    assert calls[0][1]['end_date'] == '20260914'
    assert calls[1][1]['end_date'] == '20260917'
    assert applied['akshare_count'] == 0
    assert applied['count'] == 0


def test_adapter_does_not_shift_or_repair_non_target_or_non_hk_yahoo(monkeypatch):
    import yfinance as yf

    calls = []
    def fake_download(*args, **kwargs):
        calls.append((args, dict(kwargs)))
        return object()

    monkeypatch.setattr(yf, 'download', fake_download)
    with patched_yahoo_target_boundary('2026-09-15') as applied:
        yf.download(tickers='AAPL', start='2026-01-01', end='2026-09-15', auto_adjust=True)
        yf.download(tickers='1810.HK', start='2026-01-01', end='2026-09-14', auto_adjust=True)
        yf.download(tickers='1810.HK', start='2026-01-01', end='2026-09-17', auto_adjust=True)
    assert calls[0][1]['end'] == '2026-09-15' and 'repair' not in calls[0][1]
    assert calls[1][1]['end'] == '2026-09-14' and 'repair' not in calls[1][1]
    assert calls[2][1]['end'] == '2026-09-17' and 'repair' not in calls[2][1]
    assert applied['count'] == 0
