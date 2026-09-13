import json
from pathlib import Path
from scripts.run005_v7_evaluate_ablation import evaluate


def test_evaluation_uses_same_outcomes_and_reports_deltas(tmp_path):
    rows=[
      {'code':'HK00001','status':'VALID_COMPARABLE','forward_return_pct':3.0},
      {'code':'HK00002','status':'VALID_COMPARABLE','forward_return_pct':1.0},
      {'code':'HK00003','status':'VALID_COMPARABLE','forward_return_pct':-1.0},
      {'code':'HK00004','status':'VALID_COMPARABLE','forward_return_pct':-3.0},
    ]
    # Use denominator 54 to match the real contract; only 4 comparable rows are synthetic here.
    outcome={'run_id':'champion-outcomes','anchor_id':'SSE_REBAL_20260904_EFFECTIVE_20260907','original_denominator':54,
      'horizon_results':{'1':{'rows':rows,'metrics':{
        'top_k':2,'dsa_spearman':1.0,'dsa_pairwise':{'accuracy':1.0},
        'top_k_lift_vs_comparable_mean_pct':2.0,
        'momentum_spearman':0.0,'momentum_pairwise':{'accuracy':0.5}
      }}}}
    ranked_good=[{'code':r['code'],'score':4-i} for i,r in enumerate(rows)]
    ranked_bad=[{'code':r['code'],'score':i+1} for i,r in enumerate(rows)]
    variants={}
    names=['A1_NO_MOMENTUM','A2_NO_MA_STRUCTURE','A3_NO_VOLATILITY','A4_NO_VOLUME','A5_NO_RANGE_POSITION']
    for i,n in enumerate(names):
        variants[n]={'ranked':ranked_good if i<4 else ranked_bad,'ranked_count':54,'isolated_count':0,'model_http_requests':54,'estimated_peak_cny':0.1}
    ab={'run_id':'abl','status':'RUN005_V7_ABLATION_PREDICTIONS_FROZEN','anchor_id':outcome['anchor_id'],'original_denominator':54,'outcome_data_read':False,'variants':variants,'model_http_requests':270,'cost':{'estimated_peak_cny':0.5}}
    ap=tmp_path/'a.json'; op=tmp_path/'o.json'; rp=tmp_path/'r.json'
    ap.write_text(json.dumps(ab)); op.write_text(json.dumps(outcome))
    r=evaluate(ap,op,rp)
    assert r['total_ablation_http_requests']==270
    assert r['horizons']['1']['variants']['A1_NO_MOMENTUM']['spearman_delta_vs_a0']==0.0
    assert r['horizons']['1']['variants']['A5_NO_RANGE_POSITION']['dsa_spearman'] < 0
    assert r['horizons']['1']['A6_DETERMINISTIC_MOMENTUM_CONTROL']['model_http_requests']==0
    assert r['accepted_progress_claim']=='NONE_BY_THIS_ARTIFACT_ALONE'


def test_rejects_changed_denominator(tmp_path):
    a={'status':'RUN005_V7_ABLATION_PREDICTIONS_FROZEN','outcome_data_read':False,'original_denominator':53}
    o={'original_denominator':54}
    ap=tmp_path/'a.json'; op=tmp_path/'o.json'; ap.write_text(json.dumps(a)); op.write_text(json.dumps(o))
    try: evaluate(ap,op,tmp_path/'x.json')
    except ValueError as e: assert str(e)=='denominator_mismatch'
    else: raise AssertionError('denominator mismatch not rejected')
