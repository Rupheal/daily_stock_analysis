import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from plan_o657_continuation_v3 import build

def fixture():
    u={'members':[{'code':f'{i:05d}','official_name':str(i)} for i in range(1,11)]}
    p={'current_session':{'session':'2026-09-18','official_denominator':10,'operational_denominator':8,
       'excluded_unresolved':[{'code':'00009'},{'code':'00010'}]}}
    l={'session':'2026-09-18','frozen_upstream':'abc',
       'confirmed_provider_sends':[{'code':'00001','model_call_key':'2026-09-18:00001:abc'}],
       'no_repeat_uncertain_claims':[{'code':'00004','model_call_key':'2026-09-18:00004:abc'}]}
    prev={'target_session':'2026-09-18','official_O_denominator':10,'state':'PARTIAL_O_FORMAL_CORE_PROCESSING',
          'missing_operational_members':['00003','00004','00005','00006']}
    return u,p,l,prev

def test_continuation_only_retryable_missing():
    u,p,l,prev=fixture();o=build(u,p,l,prev,100,2)
    assert o['prior_missing_count']==4
    assert o['blocked_no_repeat_missing']==['00004']
    assert o['retryable_missing_before_wave']==3
    assert o['planned_calls']==3
    flat=[x['code'] for s in o['shards'] for x in s['codes']]
    assert flat==['00003','00005','00006']

def test_budget_defer_keeps_missing():
    u,p,l,prev=fixture();o=build(u,p,l,prev,1,16)
    assert o['planned_calls']==1
    assert o['deferred_codes']==['00005','00006']

def test_invalid_missing_outside_operational_rejected():
    import pytest
    u,p,l,prev=fixture();prev['missing_operational_members'].append('00010')
    with pytest.raises(ValueError,match='INVALID_PREVIOUS_MISSING_SET'):
        build(u,p,l,prev,10)
