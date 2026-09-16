"""Bounded runtime-only HK date-boundary adapter for Gate-A recovery.

The frozen upstream checkout remains byte-for-byte unchanged. This adapter only
changes retrieval mechanics at the external runtime boundary for the one frozen
HK target session:
- yfinance ``end`` is exclusive, so target is shifted to target + 1 day and an
  already shifted target+1 is left there; repair=True is enabled;
- AkShare ``stock_hk_hist`` uses an inclusive YYYYMMDD ``end_date``.  When the
  frozen CLI asks through target+1 because the runner is already on a later day,
  the request is capped back to the frozen target session.

Native prompts, scoring, model selection, analysis code and post-fetch validation
are not changed. The caller must still enforce independent preflight and the
native input contract before any model HTTP request.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import patch


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) >= 8 and text[:8].isdigit() and '-' not in text[:10]:
        return datetime.strptime(text[:8], "%Y%m%d").date()
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _is_hk_code(value: str) -> bool:
    text = str(value or "").strip().upper()
    return text.startswith("HK") or text.endswith(".HK")


def _requested_tickers(args, kwargs):
    value = kwargs.get("tickers")
    if value is None and args:
        value = args[0]
    return value


def _is_hk_ticker_request(args, kwargs) -> bool:
    value = _requested_tickers(args, kwargs)
    if isinstance(value, str):
        parts = [p for p in value.replace(',', ' ').split() if p]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(p) for p in value]
    else:
        parts = []
    return bool(parts) and all(_is_hk_code(p) for p in parts)


@contextmanager
def patched_yahoo_target_boundary(target_session: str):
    """Patch the native HK Yahoo + AkShare retrieval boundaries for one target.

    The historical public name is kept for caller compatibility.  New receipts
    must use the returned per-provider counters instead of describing this as a
    Yahoo-only adapter.
    """
    target = _as_date(target_session)
    target_plus_one = target + timedelta(days=1)
    import yfinance as yf
    import akshare as ak

    original_download = yf.download
    original_hk_hist = ak.stock_hk_hist
    applied = {
        "count": 0,
        "yahoo_count": 0,
        "akshare_count": 0,
        "boundary_shift_count": 0,
        "repair_enable_count": 0,
        "akshare_cap_count": 0,
    }

    def bounded_download(*args, **kwargs):
        end = kwargs.get("end")
        if end is not None and _is_hk_ticker_request(args, kwargs):
            end_date = _as_date(end)
            if end_date in (target, target_plus_one):
                kwargs = dict(kwargs)
                if end_date == target:
                    kwargs["end"] = target_plus_one.isoformat()
                    applied["boundary_shift_count"] += 1
                kwargs["repair"] = True
                applied["repair_enable_count"] += 1
                applied["yahoo_count"] += 1
                applied["count"] += 1
        return original_download(*args, **kwargs)

    def bounded_hk_hist(*args, **kwargs):
        # stock_hk_hist is HK-specific.  Restrict the patch further to the exact
        # target/target+1 end boundary and leave older/far-future requests alone.
        end = kwargs.get("end_date")
        if end is None and len(args) >= 5:
            end = args[4]
        if end is not None:
            end_date = _as_date(end)
            if end_date in (target, target_plus_one):
                kwargs = dict(kwargs)
                if len(args) >= 5:
                    args = list(args)
                    args[4] = target.strftime("%Y%m%d")
                    args = tuple(args)
                else:
                    kwargs["end_date"] = target.strftime("%Y%m%d")
                applied["akshare_cap_count"] += 1
                applied["akshare_count"] += 1
                applied["count"] += 1
        return original_hk_hist(*args, **kwargs)

    with patch.object(yf, "download", bounded_download), patch.object(ak, "stock_hk_hist", bounded_hk_hist):
        yield applied
