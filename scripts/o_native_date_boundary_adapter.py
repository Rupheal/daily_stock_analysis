"""Bounded runtime-only Yahoo date-boundary adapter for Run018 recovery.

The frozen upstream checkout remains byte-for-byte unchanged. This adapter only
changes Yahoo retrieval mechanics for the one claimed HK target session:
- yfinance ``end`` is exclusive, so an end equal to target is shifted to target + 1 day;
- when the frozen CLI already supplies target + 1 day (because it runs after the
  target session), the boundary is already correct and is left unchanged;
- ``repair=True`` is enabled in both cases to materialize provider OHLC gaps
  already observed in model-free diagnostics.

Native prompts, scoring, model selection, analysis code and post-fetch validation
are not changed. The caller must still enforce the independent preflight and
native input contract before any model HTTP request.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import patch


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


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
    """Patch yfinance.download for the frozen target HK retrieval only.

    Two frozen-CLI call shapes are accepted:
    1. ``end == target``: shift to target+1 because yfinance end is exclusive.
    2. ``end == target+1``: keep the already-correct exclusive boundary and only
       enable yfinance repair materialization.

    No other date or non-HK request is changed.
    """
    target = _as_date(target_session)
    target_plus_one = target + timedelta(days=1)
    import yfinance as yf

    original_download = yf.download
    applied = {"count": 0, "boundary_shift_count": 0, "repair_enable_count": 0}

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
                applied["count"] += 1
        return original_download(*args, **kwargs)

    with patch.object(yf, "download", bounded_download):
        yield applied
