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

def test_explicit_boundary_probe_preserves_adjusted_and_raw_as_diagnostics_only():
    from xiaomi_preflight_field_diagnostics import probe_yahoo_target_boundary
    calls=[]
    class Fake:
        def history(self,**kw):
            calls.append(kw)
            f=frame(float('nan') if kw['auto_adjust'] else 10.0)
            f=f.rename(columns={'date':'Date'}).set_index('Date')
            return f
    result=probe_yahoo_target_boundary('2026-09-15',lambda code:Fake())
    assert len(calls)==2 and [v['auto_adjust'] for v in calls]==[False,True]
    assert all(v['end']=='2026-09-16' and not v['repair'] and v['keepna'] for v in calls)
    assert result[0]['frame']['fields']['open']['status']=='FINITE'
    assert result[1]['frame']['fields']['open']['invalid_count']==1
    assert all(v['diagnostic_only'] for v in result)
