"""Deterministic O-native target-session contract.

No model, network, billing, or trading side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

HK_TZ = ZoneInfo("Asia/Hong_Kong")
XHKG = "XHKG"
RULE_VERSION = "O_NATIVE_TARGET_SESSION_RULE_v1"


@dataclass(frozen=True)
class TargetSession:
    evaluation_time_hkt: datetime
    target_session: date
    rule_version: str = RULE_VERSION
    source: str = "XHKG_COMPLETED_SESSION"


def resolve_target_session(evaluation_time: datetime) -> TargetSession:
    """Return the latest XHKG session whose regular close is complete.

    Crossing midnight alone never advances the target. A new target becomes
    eligible only after the next XHKG regular session has closed.
    """
    if evaluation_time.tzinfo is None:
        raise ValueError("TARGET_SESSION_UNRESOLVED: timezone-aware evaluation_time required")
    now = evaluation_time.astimezone(HK_TZ)
    cal = xcals.get_calendar(XHKG)
    d = now.date()
    if cal.is_session(d):
        session = cal.date_to_session(d, direction="previous")
        close = cal.session_close(session).tz_convert("Asia/Hong_Kong").to_pydatetime()
        target = session.date() if now >= close else cal.previous_session(session).date()
    else:
        target = cal.date_to_session(d, direction="previous").date()
    return TargetSession(now, target)


def exclusive_end_for_daily_provider(target_session: date) -> date:
    """Return a generic exclusive daily end boundary without changing target.

    For APIs such as yfinance where ``end`` is exclusive, target+1 calendar day
    includes the target daily bar. This is a retrieval boundary only.
    """
    return target_session + timedelta(days=1)


def classify_recovery_target(original_target: date, evaluation_time: datetime) -> str:
    """Classify whether an existing zero-HTTP recovery target is still usable."""
    latest = resolve_target_session(evaluation_time).target_session
    if latest == original_target:
        return "RECOVERY_TARGET_CURRENT"
    if latest > original_target:
        return "RECOVERY_TARGET_EXPIRED_NEW_COMPLETED_SESSION"
    return "TARGET_SESSION_UNRESOLVED"


def assert_provider_latest_matches(target_session: date, provider_latest: date) -> None:
    """Fail closed when provider data has not matured to the calendar target."""
    if provider_latest != target_session:
        if provider_latest < target_session:
            raise ValueError("TARGET_DATA_NOT_MATURE")
        raise ValueError("NATIVE_TARGET_SESSION_MISMATCH")
