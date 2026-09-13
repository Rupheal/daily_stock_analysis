"""Evaluate frozen Run005 V7 ablation rankings against already-matured outcomes.

No model calls occur here. The evaluator joins each frozen ablation ranking to the
same frozen outcome rows used for the Champion and reports only the predeclared
Spearman, pairwise accuracy, Top-K lift, failure-rate and research-cost deltas.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run005_v4_ranking_uncertainty import spearman, pairwise, topk_lift


def _variant_rows(variant, outcome_rows):
    scores={r['code']:r['score'] for r in variant['ranked']}
    out=[]
    for row in outcome_rows:
        if row.get('status')!='VALID_COMPARABLE':
            continue
        code=row['code']
        if code in scores:
            out.append({'code':code,'score':scores[code],'forward_return_pct':row['forward_return_pct'],'status':'VALID_COMPARABLE'})
    return out


def evaluate(ablation_path, outcome_path, output_path):
    a=json.loads(Path(ablation_path).read_text())
    o=json.loads(Path(outcome_path).read_text())
    if a.get('outcome_data_read') is not False or a.get('status')!='RUN005_V7_ABLATION_PREDICTIONS_FROZEN':
        raise ValueError('ablation_prediction_boundary_invalid')
    if a.get('original_denominator')!=o.get('original_denominator') or a.get('original_denominator')!=54:
        raise ValueError('denominator_mismatch')
    result={
        'schema_version':1,
        'run_id':'TRI-DSA-VAL-20260913-005-V7-EVAL-R1',
        'anchor_id':a['anchor_id'],
        'original_denominator':54,
        'champion_source_run_id':o['run_id'],
        'ablation_source_run_id':a['run_id'],
        'accepted_progress_claim':'NONE_BY_THIS_ARTIFACT_ALONE',
        'horizons':{},
    }
    for h in sorted(o['horizon_results'],key=int):
        ov=o['horizon_results'][h]
        champion=ov['metrics']
        k=int(champion['top_k'])
        hv={
            'champion':{
                'dsa_spearman':champion['dsa_spearman'],
                'pairwise_accuracy':champion['dsa_pairwise']['accuracy'],
                'top_k':k,
                'top_k_lift_pp':champion['top_k_lift_vs_comparable_mean_pct'],
                'ranked_count':54,
            },
            'variants':{}
        }
        for name,v in sorted(a['variants'].items()):
            rows=_variant_rows(v,ov['rows'])
            sp=spearman(rows); pa=pairwise(rows); tl=topk_lift(rows,k)
            hv['variants'][name]={
                'n_comparable_ranked':len(rows),
                'ranked_count':v['ranked_count'],
                'isolated_count':v['isolated_count'],
                'failure_rate':v['isolated_count']/54,
                'dsa_spearman':sp,
                'spearman_delta_vs_a0':None if sp is None else sp-champion['dsa_spearman'],
                'pairwise_accuracy':pa,
                'pairwise_delta_vs_a0':None if pa is None else pa-champion['dsa_pairwise']['accuracy'],
                'top_k_lift_pp':tl,
                'top_k_lift_delta_vs_a0_pp':None if tl is None else tl-champion['top_k_lift_vs_comparable_mean_pct'],
                'model_http_requests':v['model_http_requests'],
                'estimated_peak_cny':v['estimated_peak_cny'],
            }
        # A6 deterministic momentum control is the already-frozen V6 momentum benchmark.
        hv['A6_DETERMINISTIC_MOMENTUM_CONTROL']={
            'dsa_spearman':champion['momentum_spearman'],
            'pairwise_accuracy':champion['momentum_pairwise']['accuracy'],
            'model_http_requests':0,
            'estimated_peak_cny':0.0,
            'note':'Existing V6 benchmark; not an independent model call.'
        }
        result['horizons'][h]=hv
    result['total_ablation_http_requests']=a['model_http_requests']
    result['total_ablation_estimated_peak_cny']=a['cost']['estimated_peak_cny']
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(); p.add_argument('--ablation',required=True); p.add_argument('--outcomes',required=True); p.add_argument('--output',required=True)
    a=p.parse_args(); r=evaluate(a.ablation,a.outcomes,a.output)
    print('RUN005_V7_EVAL_OK',json.dumps({'horizons':list(r['horizons']),'requests':r['total_ablation_http_requests'],'peak_cny':r['total_ablation_estimated_peak_cny']},separators=(',',':')))

if __name__=='__main__': main()
