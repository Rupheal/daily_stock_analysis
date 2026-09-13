import json
from pathlib import Path
from scripts.run005_v4_ranking_uncertainty import spearman,pairwise,topk_lift,execute


def test_metrics_and_bootstrap_reproduce(tmp_path):
    rows=[
      {'code':'HK00001','status':'VALID_COMPARABLE','score':90,'forward_return_pct':3.0},
      {'code':'HK00002','status':'VALID_COMPARABLE','score':70,'forward_return_pct':1.0},
      {'code':'HK00003','status':'VALID_COMPARABLE','score':50,'forward_return_pct':-1.0},
      {'code':'HK00004','status':'VALID_COMPARABLE','score':20,'forward_return_pct':-2.0},
    ]
    assert abs(spearman(rows)-1.0)<1e-12
    assert abs(pairwise(rows)-1.0)<1e-12
    assert abs(topk_lift(rows,1)-2.75)<1e-12
    pkg={'run_id':'x','anchor_id':'a','original_denominator':4,'horizon_results':{'1':{'rows':rows,'metrics':{'top_k':1,'dsa_spearman':1.0,'dsa_pairwise':{'accuracy':1.0},'top_k_lift_vs_comparable_mean_pct':2.75}}}}
    inp=tmp_path/'in.json'; out=tmp_path/'out.json'; inp.write_text(json.dumps(pkg))
    a=execute(inp,out,seed=123,reps=100)
    b=execute(inp,tmp_path/'out2.json',seed=123,reps=100)
    assert a==b
    assert a['horizons']['1']['point']['n']==4
    assert a['accepted_progress_claim']=='NONE_BY_THIS_ARTIFACT_ALONE'


def test_point_estimate_mismatch_fails(tmp_path):
    rows=[
      {'code':'HK00001','status':'VALID_COMPARABLE','score':3,'forward_return_pct':3.0},
      {'code':'HK00002','status':'VALID_COMPARABLE','score':2,'forward_return_pct':2.0},
      {'code':'HK00003','status':'VALID_COMPARABLE','score':1,'forward_return_pct':1.0},
    ]
    pkg={'run_id':'x','anchor_id':'a','original_denominator':3,'horizon_results':{'1':{'rows':rows,'metrics':{'top_k':1,'dsa_spearman':0.0,'dsa_pairwise':{'accuracy':1.0},'top_k_lift_vs_comparable_mean_pct':1.0}}}}
    p=tmp_path/'in.json'; p.write_text(json.dumps(pkg))
    try: execute(p,tmp_path/'out.json',reps=10)
    except ValueError as e: assert 'point_estimate_mismatch_h1' in str(e)
    else: raise AssertionError('mismatch not rejected')
