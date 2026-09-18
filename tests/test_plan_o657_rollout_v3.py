import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from plan_o657_rollout_v3 import build_plan

def fixture():
    u={'members':[{'code':f'{i:05d}','official_name':str(i)} for i in range(1,11)]}
    p={'current_session':{'session':'2026-09-18','official_denominator':10,'operational_denominator':8,
       'excluded_unresolved':[{'code':'00009'},{'code':'00010'}]}}
    frozen='abc'
    l={'frozen_upstream':frozen,'confirmed_provider_sends':[
      {'code':'00002','model_call_key':'2026-09-18:00002:abc'},
      {'code':'00005','model_call_key':'2026-09-18:00005:abc'}]}
    return u,p,l

def test_no_duplicate_spent_and_full_plan():
    u,p,l=fixture();o=build_plan(u,p,l,100,3)
    assert o['confirmed_spent_before_wave']==2
    assert o['remaining_before_wave']==6
    assert o['planned_calls']==6 and o['deferred_count']==0
    flat=[x['code'] for s in o['shards'] for x in s['codes']]
    assert '00002' not in flat and '00005' not in flat
    assert len(flat)==len(set(flat))==6
    assert o['shard_count']==3
    assert o['planned_maximum_cost_cny']=='0.60'

def test_partial_affordability_defers_in_order():
    u,p,l=fixture();o=build_plan(u,p,l,3,16)
    assert o['planned_calls']==3
    assert o['deferred_count']==3
    flat=[x['code'] for s in o['shards'] for x in s['codes']]
    assert flat==['00001','00003','00004']

def test_bad_ledger_key_rejected():
    import pytest
    u,p,l=fixture();l['confirmed_provider_sends'][0]['model_call_key']='wrong'
    with pytest.raises(ValueError,match='LEDGER_KEY'):
        build_plan(u,p,l,3)

def test_spent_outside_operational_rejected():
    import pytest
    u,p,l=fixture();l['confirmed_provider_sends'].append({'code':'00009','model_call_key':'2026-09-18:00009:abc'})
    with pytest.raises(ValueError,match='OUTSIDE_OPERATIONAL'):
        build_plan(u,p,l,3)
