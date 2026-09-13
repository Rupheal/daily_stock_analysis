"""Run005 predeclared factor ablations on one frozen PIT anchor.

A1-A5 omit exactly one predeclared feature family and reuse the frozen DeepSeek
model/output contract. A6 is a deterministic 20-session momentum control and makes
no model call. No outcome data is read. Every variant preserves the original input
denominator and freezes an append-only prediction ledger before evaluation.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts import run004_pool_safe_deepseek as model
from scripts.run005_predict_anchor import load_and_verify, sha, hk
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope

ABLATION_CONTRACT = "TRIDENT-Foundation@73766c205c0afbf56d3eba51b5991dbea1ccec75:DSA_RUN005_V7_ABLATION_CONTRACT_20260914.md"
VARIANTS = {
    "A1_NO_MOMENTUM": ["return_1d_pct","return_5d_pct","return_10d_pct","return_20d_pct"],
    "A2_NO_MA_STRUCTURE": ["ma5","ma10","ma20","bias_ma5_pct","bias_ma20_pct"],
    "A3_NO_VOLATILITY": ["realized_vol20_ann_pct"],
    "A4_NO_VOLUME": ["volume_ratio"],
    "A5_NO_RANGE_POSITION": ["position_in_20d_range"],
}
CONTROL_ID = "A6_DETERMINISTIC_MOMENTUM_CONTROL"


def input_isolations(coverage):
    return sorted([
        {"code":hk(r["code"]),"reason":"input_gate:"+str(r.get("reason") or "ISOLATED"),"source_stage":"PIT_INPUT"}
        for r in coverage.get("isolated",[])
    ], key=lambda r:r["code"])


def freeze_variant(out_root, parent_run_id, variant_id, decision, universe, ranked, isolated, input_sha, config_hash, model_version):
    ranked=sorted(ranked,key=lambda r:(r["rank"],r["code"]))
    isolated=sorted(isolated,key=lambda r:r["code"])
    envelope=build_ranking_envelope(universe,ranked,isolated,as_of=decision,claimed_scope="partial_with_isolations" if isolated else "full_pool_complete")
    ranking_sha=canonical_hash([{"code":r["code"],"rank":r["rank"],"score":r["score"],"result_sha256":r["result_sha256"]} for r in ranked])
    payload_sha=canonical_hash({"ranked":ranked,"isolated":isolated,"ranking_envelope":envelope})
    generated=datetime.now(timezone.utc).isoformat()
    run_id=f"{parent_run_id}-{variant_id}"
    package={"schema_version":1,"run_id":run_id,"variant_id":variant_id,"decision_at":decision,"generated_at":generated,"outcome_data_read":False,"original_denominator":len(universe),"ranked_count":len(ranked),"isolated_count":len(isolated),"ranked":ranked,"isolated":isolated,"ranking_envelope":envelope,"hashes":{"input_sha256":input_sha,"config_sha256":config_hash,"prediction_payload_sha256":payload_sha,"ranking_sha256":ranking_sha},"ablation_contract":ABLATION_CONTRACT}
    d=out_root/variant_id; d.mkdir(parents=True,exist_ok=False)
    pred=d/'prediction.json'; pred.write_text(json.dumps(package,ensure_ascii=False,indent=2))
    record={"run_id":run_id,"generated_at":generated,"as_of":decision,"universe_sha256":canonical_hash(universe),"input_sha256":input_sha,"model_version":model_version,"config_sha256":config_hash,"prediction_payload_sha256":payload_sha,"ranking_sha256":ranking_sha,"status":"HISTORICAL_PIT_ABLATION_FROZEN_BEFORE_EVALUATION"}
    ledger=freeze_prediction(d/'prediction-ledger',record)
    return {"variant_id":variant_id,"run_id":run_id,"ranked_count":len(ranked),"isolated_count":len(isolated),"ranking_sha256":ranking_sha,"prediction_file_sha256":sha(pred),"ledger_file":ledger.name,"ledger_file_sha256":sha(ledger)}


def execute(args, post_json=model._post_json):
    input_dir=Path(args.input_dir); config_path=Path(args.config); out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
    package_in,features,receipt,cohort,coverage,config,members=load_and_verify(input_dir,config_path)
    universe=[hk(c) for c in members]; base_isolated=input_isolations(coverage); decision=package_in['decision_at']
    api_key=os.getenv('DEEPSEEK_API_KEY')
    if not api_key and not args.dry_run: raise RuntimeError('missing_deepseek_api_key')
    total_requests=0; total_cost=0.0; total_usage={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}; manifest=[]
    for variant_id,omit in VARIANTS.items():
        ranked_raw=[]; isolated=list(base_isolated)
        for row in features['features']:
            code=hk(row['code']); facts={k:v for k,v in row.items() if k!='feature_sha256' and k not in omit}
            body=model.request_object(config['model_contract']['requested_model'],facts); reserve=model.conservative_request_reserve_cny(body)
            if total_requests>=args.max_requests:
                isolated.append({"code":code,"reason":"request_limit","source_stage":"MODEL"}); continue
            if total_cost+reserve>args.max_cny:
                isolated.append({"code":code,"reason":"budget_guard","source_stage":"MODEL"}); continue
            if args.dry_run:
                result={"score":50,"stance":"neutral","confidence":"low","reason_codes":["insufficient_edge"]}; response_model=config['model_contract']['requested_model']; usage={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
            else:
                total_requests+=1
                try:
                    provider=post_json(model.API_URL,body,api_key); result,response_model,usage=model.parse_provider_response(provider)
                except Exception as exc:
                    isolated.append({"code":code,"reason":"model_failure:"+str(exc)[:80],"source_stage":"MODEL"}); total_cost+=reserve; continue
            cost=model.usage_peak_cost_cny(usage)
            if not args.dry_run and cost<=0: cost=reserve
            total_cost+=cost
            for k in total_usage: total_usage[k]+=int(usage.get(k) or 0)
            safe={"code":code,"score":result['score'],"stance":result['stance'],"confidence":result['confidence'],"reason_codes":result['reason_codes'],"variant_feature_sha256":canonical_hash(facts),"model":response_model or config['model_contract']['requested_model']}
            safe['result_sha256']=canonical_hash(safe); ranked_raw.append(safe)
        ranked_raw.sort(key=lambda r:(-r['score'],r['code']))
        ranked=[dict(r,rank=i+1) for i,r in enumerate(ranked_raw)]
        variant_config={"contract":ABLATION_CONTRACT,"variant_id":variant_id,"omitted_fields":omit,"base_config_sha256":sha(config_path)}
        rec=freeze_variant(out,args.run_id,variant_id,decision,universe,ranked,isolated,canonical_hash([{"code":r['code'],"facts":{k:v for k,v in r.items() if k!='feature_sha256' and k not in omit}} for r in features['features']]),canonical_hash(variant_config),config['model_contract']['requested_model'])
        rec.update({"omitted_fields":omit}); manifest.append(rec)

    # deterministic control, no API call
    isolated=list(base_isolated)
    controls=[]
    for row in features['features']:
        code=hk(row['code']); val=row.get('return_20d_pct')
        if val is None:
            isolated.append({"code":code,"reason":"missing_return_20d_control","source_stage":"CONTROL"}); continue
        controls.append({"code":code,"score":float(val),"stance":"control","confidence":"control","reason_codes":["return_20d_control"],"result_sha256":canonical_hash({"code":code,"return_20d_pct":val})})
    controls.sort(key=lambda r:(-r['score'],r['code'])); controls=[dict(r,rank=i+1) for i,r in enumerate(controls)]
    control_config={"contract":ABLATION_CONTRACT,"variant_id":CONTROL_ID,"rule":"rank_desc_return_20d_pct_tie_code_asc"}
    manifest.append(freeze_variant(out,args.run_id,CONTROL_ID,decision,universe,controls,isolated,features['input_sha256'],canonical_hash(control_config),"DETERMINISTIC_RETURN20D_CONTROL_V1"))

    summary={"schema_version":1,"run_id":args.run_id,"anchor_id":package_in['anchor_id'],"decision_at":decision,"original_denominator":len(universe),"variants":manifest,"model_http_requests":total_requests,"usage":total_usage,"cost":{"basis":"peak price estimate; not actual invoice","estimated_peak_cny":round(total_cost,8),"actual_cny":None},"outcome_data_read":False,"ablation_contract":ABLATION_CONTRACT}
    (out/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print('RUN005_V7_ABLATIONS_FROZEN',json.dumps({"denominator":len(universe),"variants":len(manifest),"requests":total_requests,"estimated_peak_cny":round(total_cost,8),"ranked_counts":{r['variant_id']:r['ranked_count'] for r in manifest}}))
    return summary


def parser():
    p=argparse.ArgumentParser(); p.add_argument('--input-dir',required=True); p.add_argument('--config',required=True); p.add_argument('--output',required=True); p.add_argument('--run-id',required=True); p.add_argument('--max-requests',type=int,required=True); p.add_argument('--max-cny',type=float,required=True); p.add_argument('--dry-run',action='store_true'); return p

if __name__=='__main__': execute(parser().parse_args())
