import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from xiaomi_preflight_field_diagnostics import inspect_frame

def frame(value):
    return pd.DataFrame([{'date':'2026-09-15','open':value,'high':12.0,'low':9.0,'close':11.0,'volume':100}])

def test_valid_numeric_not_flagged_and_no_data_mutation():
    f=frame(10.0);before=f.copy(deep=True)
    r=inspect_frame(f,'synthetic');pd.testing.assert_frame_equal(f,before)
    assert all(v['status']=='FINITE' for v in r['fields'].values())

def test_nan_identifies_source_field_and_session():
    r=inspect_frame(frame(float('nan')),'synthetic-yahoo')
    assert r['fields']['open']['invalid_count']==1
    assert r['fields']['open']['examples'][0]['session']=='2026-09-15'
    assert r['source']=='synthetic-yahoo'

def test_boolean_inf_none_and_text_never_valid():
    for x in (True,float('inf'),None,'--'):
        assert inspect_frame(frame(x),'synthetic')['fields']['open']['invalid_count']==1

def test_numeric_strings_report_type_not_change_gate():
    f=frame('10.0');r=inspect_frame(f,'synthetic')
    assert r['fields']['open']['value_types']=={'builtins.str':1} and f.iloc[0]['open']=='10.0'

def test_missing_field_and_all_failures_retained():
    f=pd.concat([frame(None)]*25,ignore_index=True);f=f.drop(columns=['low'])
    r=inspect_frame(f,'synthetic')
    assert r['fields']['low']['status']=='MISSING_COLUMN'
    assert r['fields']['open']['invalid_count']==25 and len(r['fields']['open']['examples'])==20
