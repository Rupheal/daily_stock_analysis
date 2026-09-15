"""Deterministic O-native observer contract; never calls a model or provider.

The preflight must already have passed the independent HK price/volume gate.
This helper validates the exact native context presented to the frozen analyzer
without modifying frozen upstream source, prompts, scoring or model transport.
"""
from __future__ import annotations

from src.services.hk_volume_reconciliation import (
    CALIBRATION_RUN_ID,
    LATEST_SESSION_MAX_RELATIVE_DEVIATION,
    PriceVolumeReconciliationError,
    reconcile_volume_pairs,
    validate_ohlc_pairs,
)


class NativeInputContractError(ValueError):
    pass


def _day(value):
    return str(value)[:10]


def validate_native_input(preflight, context):
    """Fail closed unless native analyzer input matches the accepted preflight contract."""
    if preflight.get('passed') is not True or str(preflight.get('symbol', '')).upper() != 'HK01810':
        raise NativeInputContractError('PREFLIGHT_NOT_ACCEPTED')
    target = _day(preflight.get('target'))
    baseline = preflight.get('today') or {}
    baseline_day = _day(baseline.get('date'))
    native = (context or {}).get('today') or {}
    native_day = _day(native.get('date'))
    if not target or target == 'None' or baseline_day != target:
        raise NativeInputContractError('PREFLIGHT_SESSION_CONTRACT_INVALID')
    if native_day != target:
        raise NativeInputContractError('NATIVE_SESSION_MISMATCH')

    reconciliation = ((preflight.get('price_reconciliation') or {}).get('volume') or {})
    if reconciliation.get('calibration_run_id') != CALIBRATION_RUN_ID:
        raise NativeInputContractError('PREFLIGHT_VOLUME_CALIBRATION_UNVERIFIED')
    if reconciliation.get('latest_session_max_relative_deviation') != LATEST_SESSION_MAX_RELATIVE_DEVIATION:
        raise NativeInputContractError('PREFLIGHT_VOLUME_BOUND_UNVERIFIED')
    if reconciliation.get('unit_semantics') != 'same-scale empirically verified; no 100x/0.01x pattern in calibration':
        raise NativeInputContractError('PREFLIGHT_VOLUME_UNIT_SEMANTICS_UNVERIFIED')

    expected = baseline.get('ohlc', baseline)
    try:
        validate_ohlc_pairs((key, native.get(key), expected.get(key)) for key in ('open','high','low','close'))
    except PriceVolumeReconciliationError as exc:
        raise NativeInputContractError('NATIVE_' + str(exc)) from None

    expected_volume = baseline.get('volume', expected.get('volume'))
    try:
        volume = reconcile_volume_pairs(
            [(target, native.get('volume'), expected_volume)],
            target,
            corporate_action_dates=(),
            unit_semantics_verified=True,
        )
    except PriceVolumeReconciliationError as exc:
        raise NativeInputContractError('NATIVE_' + str(exc)) from None
    return {
        'validated': True,
        'target': target,
        'volume_status': volume.get('latest_session_status'),
        'volume_relative_deviation': volume.get('latest_session_relative_deviation'),
        'calibration_run_id': CALIBRATION_RUN_ID,
    }
