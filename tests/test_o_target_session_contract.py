from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.o_target_session_contract import (
    assert_provider_latest_matches,
    classify_recovery_target,
    exclusive_end_for_daily_provider,
    resolve_target_session,
)

HKT = ZoneInfo("Asia/Hong_Kong")


def t(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=HKT)


def test_midnight_crossing_does_not_advance_target():
    assert resolve_target_session(t("2026-09-15T23:59:00")).target_session == date(2026, 9, 15)
    assert resolve_target_session(t("2026-09-16T00:03:00")).target_session == date(2026, 9, 15)


def test_preopen_and_intraday_keep_previous_completed_session():
    assert resolve_target_session(t("2026-09-16T08:30:00")).target_session == date(2026, 9, 15)
    assert resolve_target_session(t("2026-09-16T14:00:00")).target_session == date(2026, 9, 15)


def test_after_regular_close_advances_target():
    assert resolve_target_session(t("2026-09-16T16:10:00")).target_session == date(2026, 9, 16)


def test_weekend_resolves_previous_completed_session():
    assert resolve_target_session(t("2026-09-19T12:00:00")).target_session == date(2026, 9, 18)


def test_exclusive_provider_boundary_is_not_target():
    target = date(2026, 9, 15)
    assert exclusive_end_for_daily_provider(target) == date(2026, 9, 16)


def test_recovery_remains_current_until_new_session_closes():
    target = date(2026, 9, 15)
    assert classify_recovery_target(target, t("2026-09-16T00:03:00")) == "RECOVERY_TARGET_CURRENT"
    assert classify_recovery_target(target, t("2026-09-16T15:59:00")) == "RECOVERY_TARGET_CURRENT"


def test_recovery_expires_after_new_completed_session():
    target = date(2026, 9, 15)
    assert classify_recovery_target(target, t("2026-09-16T16:10:00")) == "RECOVERY_TARGET_EXPIRED_NEW_COMPLETED_SESSION"


def test_provider_lag_fails_closed_without_target_rollback():
    with pytest.raises(ValueError, match="TARGET_DATA_NOT_MATURE"):
        assert_provider_latest_matches(date(2026, 9, 15), date(2026, 9, 14))


def test_provider_ahead_or_wrong_session_fails_closed():
    with pytest.raises(ValueError, match="NATIVE_TARGET_SESSION_MISMATCH"):
        assert_provider_latest_matches(date(2026, 9, 15), date(2026, 9, 16))


def test_naive_time_rejected():
    with pytest.raises(ValueError, match="TARGET_SESSION_UNRESOLVED"):
        resolve_target_session(datetime(2026, 9, 16, 0, 3))
