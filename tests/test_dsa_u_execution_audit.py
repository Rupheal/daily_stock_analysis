"""Source failures must never become execution evidence."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('u_audit', Path(__file__).parents[1]/'scripts/dsa_u_execution_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

def test_real_bad_params_is_explicit_source_failure():
    with pytest.raises(ValueError, match='TENCENT_SOURCE_REJECTED'):
        audit.tencent_rows(b'{"code":1,"msg":"bad params","data":[]}', '00700', '2026-09-14')

def test_adjusted_only_cannot_become_raw_evidence():
    raw = json.dumps({'code':0,'data':{'hk00700':{'qfqday':[['2026-09-14',1,1,1,1,1]]}}})
    with pytest.raises(ValueError, match='NO_QFQ_SUBSTITUTION'):
        audit.tencent_rows(raw, '00700', '2026-09-14')

def test_future_daily_bar_excluded():
    raw = json.dumps({'code':0,'data':{'hk00700':{'day':[['2026-09-15',1,1,1,1,1]]}}})
    assert audit.tencent_rows(raw, '00700', '2026-09-14') == {}

def test_nonfinite_and_bad_geometry_rejected():
    assert not audit.valid(dict(open=2,high=1,low=1,close=1,volume=1))
    assert not audit.valid(dict(open=1,high=1,low=1,close=float('nan'),volume=1))
