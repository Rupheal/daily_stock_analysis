"""Deterministic O-native observer contract; never imports or mutates frozen ``src``.

This helper deliberately contains the already-accepted calibration constants and
minimal reconciliation math locally.  The prior implementation imported
``src.services.hk_volume_reconciliation`` before the frozen checkout was placed
at the front of ``sys.path``; that could pre-load the research fork's ``src``
package and contaminate the supposedly original-native process.  Keeping this
observer standalone preserves the frozen upstream module namespace.
"""
from __future__ import annotations

import math
import re

CALIBRATION_RUN_ID = 34983641578
LATEST_SESSION_MAX_RELATIVE_DEVIATION = 0.00170985
OHLC_ABSOLUTE_TOLERANCE = 0.005
UNIT_SEMANTICS = 'same-scale empirically verified; no 100x/0.01x pattern in calibration'


class NativeInputContractError(ValueError):
    pass


def _day(value):
    return str(value)[:10]


def _finite(value, code):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise NativeInputContractError(code) from None
    if not math.isfinite(x):
        raise NativeInputContractError(code)
    return x


def validate_native_input(preflight, context):
    """Fail closed unless native analyzer input matches the accepted preflight contract."""
    symbol = str(preflight.get('symbol', '')).upper()
    if preflight.get('passed') is not True or not re.fullmatch(r'HK[0-9]{5}', symbol):
        raise NativeInputContractError('PREFLIGHT_NOT_ACCEPTED')
    native_code = str((context or {}).get('code', '')).upper()
    if native_code and native_code != symbol:
        raise NativeInputContractError('NATIVE_SYMBOL_MISMATCH')
    if symbol != 'HK01810' and not native_code:
        raise NativeInputContractError('NATIVE_SYMBOL_REQUIRED_FOR_POOL')
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
    if reconciliation.get('unit_semantics') != UNIT_SEMANTICS:
        raise NativeInputContractError('PREFLIGHT_VOLUME_UNIT_SEMANTICS_UNVERIFIED')

    expected = baseline.get('ohlc', baseline)
    for key in ('open', 'high', 'low', 'close'):
        left = _finite(native.get(key), 'NATIVE_PRICE_NONFINITE_' + key.upper())
        right = _finite(expected.get(key), 'NATIVE_PRICE_NONFINITE_' + key.upper())
        if abs(left - right) > OHLC_ABSOLUTE_TOLERANCE:
            raise NativeInputContractError('NATIVE_PRICE_DISAGREEMENT_' + key.upper())

    left = _finite(native.get('volume'), 'NATIVE_VOLUME_NONFINITE')
    right = _finite(baseline.get('volume', expected.get('volume')), 'NATIVE_VOLUME_NONFINITE')
    if left < 0 or right < 0:
        raise NativeInputContractError('NATIVE_VOLUME_NONFINITE')
    if left == 0 or right == 0:
        if left != right:
            raise NativeInputContractError('NATIVE_VOLUME_ZERO_SEMANTICS_MISMATCH')
        deviation = 0.0
        status = 'exact'
    else:
        deviation = abs(left / right - 1.0)
        if left == right:
            status = 'exact'
        elif deviation <= LATEST_SESSION_MAX_RELATIVE_DEVIATION:
            status = 'bounded_provider_reconciliation'
        else:
            raise NativeInputContractError('NATIVE_VOLUME_LATEST_OUTSIDE_CALIBRATED_BOUND')

    return {
        'validated': True,
        'target': target,
        'volume_status': status,
        'volume_relative_deviation': deviation,
        'calibration_run_id': CALIBRATION_RUN_ID,
    }


def validate_native_history_database(preflight, database):
    """For new pool preflights bind every independently checked native input bar.

    Historical Gate-A artifacts do not contain this optional member-window contract.
    No research src module or mutable strategy is imported.
    """
    expected=preflight.get('validated_native_history')
    if expected is None:return None
    import sqlite3
    window=preflight.get('native_history_window') or {}
    if len(expected)<21 or window.get('count')!=len(expected):raise NativeInputContractError('NATIVE_HISTORY_CONTRACT_INVALID')
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as con:
        rows=con.execute('SELECT date,open,high,low,close,volume FROM stock_daily WHERE code=? COLLATE NOCASE ORDER BY date',(preflight['symbol'],)).fetchall()
    if len(rows)!=len(expected):raise NativeInputContractError('NATIVE_HISTORY_WINDOW_CHANGED')
    for actual,ref in zip(rows,expected):
        if str(actual[0])[:10]!=str(ref['date'])[:10]:raise NativeInputContractError('NATIVE_HISTORY_DATE_CHANGED')
        for i,k in enumerate(('open','high','low','close'),1):
            if abs(_finite(actual[i],'NATIVE_HISTORY_NONFINITE')-_finite(ref[k],'NATIVE_HISTORY_NONFINITE'))>OHLC_ABSOLUTE_TOLERANCE:raise NativeInputContractError('NATIVE_HISTORY_PRICE_CHANGED')
        if _finite(actual[5],'NATIVE_HISTORY_NONFINITE')!=_finite(ref['volume'],'NATIVE_HISTORY_NONFINITE'):raise NativeInputContractError('NATIVE_HISTORY_VOLUME_CHANGED')
    return {'passed':True,'count':len(rows),'first':window['first'],'last':window['last'],'every_native_bar_validated':True}
