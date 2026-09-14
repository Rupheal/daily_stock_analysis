import copy
import pytest
from scripts.run008_recovery_pair import prepare
from scripts.run004_pool_safe_deepseek import request_object
from src.services.dsa_prediction_ledger import canonical_hash

def fixture():
    f={'code':'HK00001','as_of':'2026-09-11','realized_vol20_ann_pct':10,'return_1d_pct':1}
    r={'as_of':'2026-09-11','feature_input_sha256':'fixture','rows':[{'code':'HK00001','features':f,'feature_sha256':canonical_hash(f)}],'retained':[{'code':'HK00002','reason':'RAW_SOURCE_CONFLICT'}]}
    u={'full_union_verified':True,'member_count':3,'members':[{'code':c} for c in ['HK00001','HK00002','HK02922']]}
    c={'data_as_of':'2026-09-11','recovery_feature_input_sha256':'fixture'}
    return r,u,c

def test_denominator_and_new_identity_quarantine():
    r,u,c=fixture();before=copy.deepcopy(r);m,good,bad=prepare(r,u,c)
    assert len(m)==3 and len(good)==1 and len(bad)==2 and r==before
    assert bad[-1]['reason']=='NEW_CODE_HISTORY_NOT_VERIFIED'

def test_tampered_features_rejected():
    r,u,c=fixture();r['rows'][0]['features']['return_1d_pct']=999
    with pytest.raises(ValueError,match='feature_hash'):prepare(r,u,c)

def test_ablation_is_only_one_input_omission():
    r,u,c=fixture();f=r['rows'][0]['features'];a=request_object('same-model',f);b=request_object('same-model',{k:v for k,v in f.items() if k!='realized_vol20_ann_pct'})
    import json
    ax=json.loads(a['messages'][1]['content']);bx=json.loads(b['messages'][1]['content']);del ax['facts']['realized_vol20_ann_pct'];assert ax==bx
    a['messages'][1]=b['messages'][1];assert a==b
