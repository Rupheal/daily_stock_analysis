"""Evidence-bounded reconciliation for HK daily volume across providers.

The calibration evidence comes from GitHub Actions Run 34983641578, executed
twice without model credentials. Across 8 comparable liquid HK names and 1,000
non-zero overlapping sessions per run, 992 sessions matched exactly and all 8
mismatches were the latest session. Historical mismatches were zero; no 100x or
0.01x unit pattern was observed. The largest latest-session relative deviation
was 0.00170985. No margin is added beyond that observed maximum.
"""
from __future__ import annotations

import math

CALIBRATION_RUN_ID = 34983641578
CALIBRATION_ATTEMPTS = 2
CALIBRATION_REQUESTED_STOCKS = 14
CALIBRATION_COMPARABLE_STOCKS = 8
CALIBRATION_VALID_SESSIONS = 1000
CALIBRATION_EXACT_SESSIONS = 992
CALIBRATION_HISTORICAL_MISMATCHES = 0
CALIBRATION_LATEST_MISMATCHES = 8
CALIBRATION_NEAR_100X = 0
CALIBRATION_NEAR_0_01X = 0
LATEST_SESSION_MAX_RELATIVE_DEVIATION = 0.00170985


class VolumeReconciliationError(ValueError):
    """Fixed semantic failure, safe to surface in sanitized diagnostics."""


def validate_latest_session(primary_last, independent_last, target):
    if primary_last != target or independent_last != target:
        raise VolumeReconciliationError('VOLUME_PROVIDER_STALE_OR_WRONG_SESSION')


def reconcile_volume_pairs(pairs, target, corporate_action_dates=()):
    """Reconcile iterable of (date, primary_volume, independent_volume).

    Historical sessions remain exact-only because calibration observed zero
    historical mismatches. Only the target/latest session may use the bounded
    provider-reconciliation ceiling observed in the two calibration attempts.
    """
    corporate = {str(x)[:10] for x in corporate_action_dates}
    latest_seen = False
    exact = 0
    historical_exact = 0
    latest_status = None
    latest_relative_deviation = None

    for date, primary, independent in pairs:
        day = str(date)[:10]
        if day in corporate:
            raise VolumeReconciliationError('VOLUME_CORPORATE_ACTION_NOT_ISOLATED')
        try:
            left = float(primary)
            right = float(independent)
        except (TypeError, ValueError):
            raise VolumeReconciliationError('VOLUME_NONFINITE') from None
        if not math.isfinite(left) or not math.isfinite(right) or left < 0 or right < 0:
            raise VolumeReconciliationError('VOLUME_NONFINITE')
        if right == 0 or left == 0:
            if left != right:
                raise VolumeReconciliationError('VOLUME_ZERO_SEMANTICS_MISMATCH')
            deviation = 0.0
        else:
            deviation = abs(left / right - 1.0)

        if day == target:
            latest_seen = True
            latest_relative_deviation = deviation
            if left == right:
                exact += 1
                latest_status = 'exact'
            elif deviation <= LATEST_SESSION_MAX_RELATIVE_DEVIATION:
                latest_status = 'bounded_provider_reconciliation'
            else:
                raise VolumeReconciliationError('VOLUME_LATEST_OUTSIDE_CALIBRATED_BOUND')
        else:
            if left != right:
                # This also fails obvious 100x / 0.01x unit mismatches without
                # inventing an arbitrary unit-ratio tolerance band.
                raise VolumeReconciliationError('VOLUME_HISTORICAL_NOT_EXACT')
            exact += 1
            historical_exact += 1

    if not latest_seen:
        raise VolumeReconciliationError('VOLUME_TARGET_SESSION_MISSING')

    return {
        'calibration_run_id': CALIBRATION_RUN_ID,
        'calibration_attempts': CALIBRATION_ATTEMPTS,
        'calibration_comparable_stocks': CALIBRATION_COMPARABLE_STOCKS,
        'calibration_valid_sessions': CALIBRATION_VALID_SESSIONS,
        'calibration_historical_mismatches': CALIBRATION_HISTORICAL_MISMATCHES,
        'calibration_latest_mismatches': CALIBRATION_LATEST_MISMATCHES,
        'latest_session_max_relative_deviation': LATEST_SESSION_MAX_RELATIVE_DEVIATION,
        'latest_session_status': latest_status,
        'latest_session_relative_deviation': latest_relative_deviation,
        'historical_sessions_exact': historical_exact,
        'exact_sessions_total': exact,
        'unit_semantics': 'same-scale empirically verified; no 100x/0.01x pattern in calibration',
    }
