import json
from argparse import Namespace
from scripts.run005_bootstrap_ranking_quality import execute


def test_bootstrap_is_deterministic_and_reports_all_horizons(tmp_path):
    src={'anchor_id':'A1','horizon_results':{}}
    for h in ('1','3','5'):
        rows=[]
        for i in range(12):
            rows.append({'code':f'HK{i:05d}','status':'VALID_COMPARABLE','score':100-i,'forward_return_pct':float(i-6)})
        src['horizon_results'][h]={'rows':rows}
    p=tmp_path/'in.json'; p.write_text(json.dumps(src))
    o1=tmp_path/'o1.json'; o2=tmp_path/'o2.json'
    a=execute(Namespace(input=str(p),output=str(o1),reps=200))
    b=execute(Namespace(input=str(p),output=str(o2),reps=200))
    assert a==b
    assert set(a['horizons'])=={'1','3','5'}
    for v in a['horizons'].values():
        assert v['n']==12
        assert v['ci95']['spearman']['valid_reps']>0
        assert v['ci95']['pairwise_accuracy']['valid_reps']>0
        assert v['ci95']['top_k_lift_pct']['valid_reps']==200


def test_bootstrap_handles_empty_comparable_subset(tmp_path):
    src={'anchor_id':'A1','horizon_results':{'1':{'rows':[{'code':'HK00001','status':'SUSPENDED_OR_NO_OFFICIAL_CLOSE','score':50,'forward_return_pct':None}]}}}
    p=tmp_path/'in.json'; p.write_text(json.dumps(src)); o=tmp_path/'o.json'
    result=execute(Namespace(input=str(p),output=str(o),reps=20))
    h=result['horizons']['1']
    assert h['n']==0
    assert h['point']['spearman'] is None
    assert h['ci95']['spearman']['valid_reps']==0
