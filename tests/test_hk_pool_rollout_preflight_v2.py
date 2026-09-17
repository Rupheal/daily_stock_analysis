import sys
from datetime import date,timedelta
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_hk_pool_rollout_preflight_v2 import build_preflight
from prepare_hk_pool_rollout_preflight import LATEST_VOLUME_MAX_RELATIVE_DEVIATION

def rows():
    start=date(2026,8,27);out=[]
    for i in range(22):
        d=(start+timedelta(days=i)).isoformat();px=10+i*0.1
        out.append({'date':d,'open':px,'high':px+0.3,'low':px-0.2,'close':px+0.1,'volume':100000+i*100,
                    'amount':None,'pct_chg':None,'ma5':px,'ma10':px,'ma20':px,'volume_ratio':1.0,'data_source':'Yahoo'})
    return out

def base():
    n=rows();target=n[-1]['date']
    ind=[{k:r[k] for k in ('date','open','high','low','close','volume')} for r in n]
    # Historical adjustment conflict is informational in v2.
    ind[0]['open']+=0.03
    universe={'full_union_verified':True,'_sha256':'u','members':[{'code':'00001','official_name':'TEST','channels':['SSE']}]}
    cache={'target_session':target,'_sha256':'c','histories':{'hk00001':n}}
    paths=['docs/runtime/RUN050_O_SESSION_LISTING_ADJUDICATION.json','docs/runtime/RUN051_O_THIRD_SOURCE_ADJUDICATION.json','docs/runtime/RUN052_O_GEOMETRY_ADJUDICATION.json']
    plan={'state':'PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN','target_session':target,'_sha256':'p',
          'rollout':{'ready_codes':['00001']},'isolation':{'codes':[]},'input_sha256':{p:'a'*64 for p in paths}}
    src={'provider':'Tencent','url':'https://example.com','retrieved_at':'2026-09-18T00:00:00+00:00','sha256':'x'}
    return n,target,ind,universe,cache,plan,src

def test_prior_adjudicated_history_allows_historical_adjustment_difference_but_not_hides_it():
    n,target,ind,u,c,p,s=base()
    out=build_preflight('00001',target,u,c,p,ind,s)
    diag=out['price_reconciliation']['historical_cross_provider_diagnostic']
    assert out['passed'] is True
    assert diag['ohlc_mismatch_sessions']==1
    assert diag['admission_use'].startswith('INFORMATIONAL_ONLY')
    assert out['news_search_performed'] is False
    assert out['validated_native_history']==n

def test_target_ohlc_still_fails_closed():
    n,target,ind,u,c,p,s=base();ind[-1]['close']+=0.02
    with pytest.raises(ValueError,match='TARGET_SESSION_OHLC'):
        build_preflight('00001',target,u,c,p,ind,s)

def test_target_volume_still_uses_frozen_calibration():
    n,target,ind,u,c,p,s=base()
    ind[-1]['volume']=n[-1]['volume']/(1+LATEST_VOLUME_MAX_RELATIVE_DEVIATION+0.001)
    with pytest.raises(ValueError,match='TARGET_SESSION_VOLUME'):
        build_preflight('00001',target,u,c,p,ind,s)

def test_code_must_be_in_prior_ready_set():
    n,target,ind,u,c,p,s=base();p['rollout']['ready_codes']=[]
    with pytest.raises(ValueError,match='CODE_NOT_PRIOR'):
        build_preflight('00001',target,u,c,p,ind,s)
