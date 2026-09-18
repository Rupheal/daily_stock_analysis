import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from prepare_hk_o_operational_preflight_v3 import build_preflight

def fixture():
    target='2026-09-18'
    universe={'full_union_verified':True,'members':[{'code':'00001','official_name':'A','channels':['SSE']} for _ in range(1)]}
    universe['members'] += [{'code':f'{i:05d}','official_name':str(i),'channels':['SSE']} for i in range(2,661)]
    universe['_sha256']='a'*64
    native=[
      {'date':f'2026-08-{i:02d}' if i<=31 else f'2026-09-{i-31:02d}','open':10,'high':11,'low':9,'close':10,'volume':100,'amount':1000}
      for i in range(1,50)
    ]
    native[-2]['date']='2026-09-17';native[-1]['date']=target
    cache={'target_session':target,'histories':{'hk00001':native},'_sha256':'b'*64}
    policy={'policy_id':'DSA-O-UNRESOLVED-EXCLUSION-v1','_sha256':'c'*64,'current_session':{
      'session':target,'official_denominator':660,'operational_denominator':657,'excluded_count':3,
      'excluded_unresolved':[{'code':'00853'},{'code':'02172'},{'code':'02252'}]
    }}
    independent=[dict(native[-1])]
    source={'provider':'Tencent HK qfq daily'}
    return target,universe,cache,policy,independent,source

def test_current_operational_member_passes():
    t,u,c,p,i,s=fixture();o=build_preflight('00001',t,u,c,p,i,s)
    assert o['passed'] is True
    assert o['operational_pool']['base_operational_denominator']==657
    assert o['risk_review_complete'] is False
    assert o['execution_contract']['realtime_quote_available'] is False

def test_policy_excluded_member_fails():
    t,u,c,p,i,s=fixture()
    u['members'][0]['code']='00853';c['histories']={'hk00853':c['histories']['hk00001']}
    import pytest
    with pytest.raises(ValueError,match='POLICY_EXCLUDED'):
        build_preflight('00853',t,u,c,p,i,s)

def test_target_volume_disagreement_fails():
    t,u,c,p,i,s=fixture();i[0]['volume']=1
    import pytest
    with pytest.raises(ValueError,match='VOLUME_OUTSIDE'):
        build_preflight('00001',t,u,c,p,i,s)

def test_session_mismatch_fails():
    t,u,c,p,i,s=fixture();p['current_session']['session']='2026-09-17'
    import pytest
    with pytest.raises(ValueError,match='POLICY_SESSION'):
        build_preflight('00001',t,u,c,p,i,s)
