"""Bounded runtime-only Yahoo date-boundary adapter for Run018 recovery.

The frozen upstream checkout remains byte-for-byte unchanged.  This adapter only
changes Yahoo retrieval mechanics for the one claimed HK target session:
- yfinance ``end`` is treated as exclusive, so target -> target + 1 day;
- ``repair=True`` is enabled to materialize provider OHLC gaps already proven by
  model-free diagnostics.

Native prompts, scoring, model selection, analysis code and post-fetch validation
are not changed.  The caller must still enforce the independent preflight and
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


@contextmanager
def patched_yahoo_target_boundary(target_session: str):
    """Patch only the frozen upstream Yahoo history call for the target HK day."""
    target = _as_date(target_session)
    from data_provider.yfinance_fetcher import YfinanceFetcher
    import yfinance as yf

    original_fetch = YfinanceFetcher._fetch_raw_data
    original_download = yf.download
    applied = {"count": 0}

    def bounded_download(*args, **kwargs):
        end = kwargs.get("end")
        if end is not None and _as_date(end) == target:
            kwargs = dict(kwargs)
            kwargs["end"] = (target + timedelta(days=1)).isoformat()
            kwargs["repair"] = True
            applied["count"] += 1
        return original_download(*args, **kwargs)

    def bounded_fetch(self, stock_code, start_date, end_date):
        if _is_hk_code(stock_code) and _as_date(end_date) == target:
            with patch.object(yf, "download", bounded_download):
                return original_fetch(self, stock_code, start_date, end_date)
        return original_fetch(self, stock_code, start_date, end_date)

    with patch.object(YfinanceFetcher, "_fetch_raw_data", bounded_fetch):
        yield applied
