"""Bounded runtime-only Yahoo date-boundary adapter for Run018 recovery.

The frozen upstream checkout remains byte-for-byte unchanged. This adapter only
changes Yahoo retrieval mechanics for the one claimed HK target session:
- yfinance ``end`` is treated as exclusive, so target -> target + 1 day;
- ``repair=True`` is enabled to materialize provider OHLC gaps already proven by
  model-free diagnostics.

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
    """Patch yfinance.download globally for only the exact target HK request.

    The native provider can be imported through more than one module identity in
    the frozen CLI. Patching the installed yfinance module function avoids that
    identity ambiguity while keeping the intervention narrower than altering any
    native source file or model logic.
    """
    target = _as_date(target_session)
    import yfinance as yf

    original_download = yf.download
    applied = {"count": 0}

    def bounded_download(*args, **kwargs):
        end = kwargs.get("end")
        if (
            end is not None
            and _as_date(end) == target
            and _is_hk_ticker_request(args, kwargs)
        ):
            kwargs = dict(kwargs)
            kwargs["end"] = (target + timedelta(days=1)).isoformat()
            kwargs["repair"] = True
            applied["count"] += 1
        return original_download(*args, **kwargs)

    with patch.object(yf, "download", bounded_download):
        yield applied
