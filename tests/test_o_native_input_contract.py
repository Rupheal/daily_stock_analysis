from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from o_native_input_contract import NativeInputContractError, validate_native_input
from src.services.hk_volume_reconciliation import CALIBRATION_RUN_ID, LATEST_SESSION_MAX_RELATIVE_DEVIATION

UNIT='same-scale empirically verified; no 100x/0.01x pattern in calibration'

def preflight(volume=1000000.0):
    return {
        'passed':True,'symbol':'HK01810','target':'2026-09-15',
        'today':{'date':'2026-09-15','open':10.0,'high':11.0,'low':9.0,'close':10.5,'volume':volume},
        'price_reconciliation':{'volume':{
            'calibration_run_id':CALIBRATION_RUN_ID,
            'latest_session_max_relative_deviation':LATEST_SESSION_MAX_RELATIVE_DEVIATION,
            'unit_semantics':UNIT,
        }},
    }

def context(**overrides):
    row={'date':'2026-09-15','open':10.0,'high':11.0,'low':9.0,'close':10.5,'volume':1000000.0}
    row.update(overrides)
    return {'today':row}

def test_exact_input_passes():
    assert validate_native_input(preflight(),context())['validated'] is True

def test_latest_calibrated_provider_revision_passes():
    # Inside the empirically observed latest-session bound; same shares scale.
    r=validate_native_input(preflight(),context(volume=999000.0))
    assert r['volume_status']=='bounded_provider_reconciliation'

def test_session_mismatch_fails_before_volume():
    with pytest.raises(NativeInputContractError,match='NATIVE_SESSION_MISMATCH'):
        validate_native_input(preflight(),context(date='2026-09-14'))

def test_large_latest_volume_mismatch_fails():
    with pytest.raises(NativeInputContractError,match='NATIVE_VOLUME_LATEST_OUTSIDE_CALIBRATED_BOUND'):
        validate_native_input(preflight(),context(volume=900000.0))

def test_100x_unit_mismatch_fails():
    with pytest.raises(NativeInputContractError,match='NATIVE_VOLUME_LATEST_OUTSIDE_CALIBRATED_BOUND'):
        validate_native_input(preflight(),context(volume=100000000.0))

def test_001x_unit_mismatch_fails():
    with pytest.raises(NativeInputContractError,match='NATIVE_VOLUME_LATEST_OUTSIDE_CALIBRATED_BOUND'):
        validate_native_input(preflight(),context(volume=10000.0))

def test_ohlc_mismatch_fails_even_when_volume_matches():
    with pytest.raises(NativeInputContractError,match='NATIVE_PRICE_DISAGREEMENT_CLOSE'):
        validate_native_input(preflight(),context(close=10.6))

def test_missing_calibration_fails_closed():
    p=preflight(); p['price_reconciliation']={}
    with pytest.raises(NativeInputContractError,match='PREFLIGHT_VOLUME_CALIBRATION_UNVERIFIED'):
        validate_native_input(p,context())

def test_wrong_bound_fails_closed():
    p=preflight(); p['price_reconciliation']['volume']['latest_session_max_relative_deviation']=0.2
    with pytest.raises(NativeInputContractError,match='PREFLIGHT_VOLUME_BOUND_UNVERIFIED'):
        validate_native_input(p,context())

def test_nonfinite_volume_fails():
    with pytest.raises(NativeInputContractError,match='NATIVE_VOLUME_NONFINITE'):
        validate_native_input(preflight(),context(volume=float('nan')))


def test_member_history_contract_rejects_changed_nonlatest_bar(tmp_path):
    import sqlite3
    from o_native_input_contract import validate_native_history_database,NativeInputContractError
    db=tmp_path/'data.db'
    conn=sqlite3.connect(db);conn.execute('CREATE TABLE stock_daily(code,date,open,high,low,close,volume)')
    rows=[{'date':f'2026-08-{i:02}','open':10,'high':11,'low':9,'close':10,'volume':100} for i in range(1,22)]
    conn.executemany('INSERT INTO stock_daily VALUES (?,?,?,?,?,?,?)',[('hk00700',r['date'],10,11,9,10,100) for r in rows]);conn.commit()
    p={'symbol':'HK00700','validated_native_history':rows,'native_history_window':{'first':rows[0]['date'],'last':rows[-1]['date'],'count':21}}
    assert validate_native_history_database(p,db)['every_native_bar_validated']
    conn.execute("UPDATE stock_daily SET volume=101 WHERE date='2026-08-01'");conn.commit()
    import pytest
    with pytest.raises(NativeInputContractError,match='VOLUME_CHANGED'):validate_native_history_database(p,db)
    conn.close()
