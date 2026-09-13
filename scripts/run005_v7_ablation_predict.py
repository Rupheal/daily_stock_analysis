"""Freeze predeclared Run005 V7 ablation rankings before ablation outcome evaluation.

The five DeepSeek variants differ from the frozen Champion only by omission of one
predeclared feature family. No outcome data is read. Each variant preserves the
original anchor denominator and gets its own append-only prediction ledger record.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts import run004_pool_safe_deepseek as model
from scripts.run005_predict_anchor import load_and_verify, hk, sha, EXPECTED_CONFIG_ID
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope

VARIANTS = {
    "A1_NO_MOMENTUM": {"return_1d_pct", "return_5d_pct", "return_10d_pct", "return_20d_pct"},
    "A2_NO_MA_STRUCTURE": {"ma5", "ma10", "ma20", "bias_ma5_pct", "bias_ma20_pct"},
    "A3_NO_VOLATILITY": {"realized_vol20_ann_pct"},
    "A4_NO_VOLUME": {"volume_ratio"},
    "A5_NO_RANGE_POSITION": {"position_in_20d_range"},
}


def _safe_result(code, result, response_model, usage, feature_hash, cost):
    row = {
        "code": code,
        "score": result["score"],
        "stance": result["stance"],
        "confidence": result["confidence"],
        "reason_codes": result["reason_codes"],
        "feature_sha256": feature_hash,
        "model": response_model,
        "usage": {k: int((usage or {}).get(k) or 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "peak_cost_estimate_cny": round(cost, 8),
    }
    row["result_sha256"] = canonical_hash({k: row[k] for k in ("code", "score", "stance", "confidence", "reason_codes", "feature_sha256", "model")})
    return row


def execute(args, post_json=model._post_json):
    input_dir = Path(args.input_dir); config_path = Path(args.config); out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    package_in, features, receipt, cohort, coverage, config, members = load_and_verify(input_dir, config_path)
    if package_in["anchor_id"] != "SSE_REBAL_20260904_EFFECTIVE_20260907":
        raise ValueError("unexpected_ablation_anchor")
    if package_in["original_denominator"] != 54 or package_in["eligible_count"] != 54 or package_in["isolated_count"] != 0:
        raise ValueError("ablation_requires_verified_54_of_54_input")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key and not args.dry_run:
        raise RuntimeError("missing_deepseek_api_key")

    universe = [hk(c) for c in members]
    global_requests = 0; global_cost = 0.0
    global_usage = {"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
    variants_out = {}
    started = datetime.now(timezone.utc).isoformat()

    for variant, omitted in VARIANTS.items():
        ranked_raw=[]; isolated=[]; variant_usage={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}; variant_cost=0.0; variant_requests=0
        for original in features["features"]:
            code=hk(original["code"])
            facts={k:v for k,v in original.items() if k not in omitted and k != "feature_sha256"}
            if any(k in facts for k in omitted): raise AssertionError("omitted_feature_leak")
            feature_hash=canonical_hash(facts)
            body=model.request_object(config["model_contract"]["requested_model"], facts)
            reserve=model.conservative_request_reserve_cny(body)
            if global_requests >= args.max_requests:
                isolated.append({"code":code,"reason":"global_request_limit","source_stage":"MODEL"}); continue
            if global_cost + reserve > args.max_cny:
                isolated.append({"code":code,"reason":"global_budget_guard","source_stage":"MODEL"}); continue
            if args.dry_run:
                result={"score":50,"stance":"neutral","confidence":"low","reason_codes":["insufficient_edge"]}
                response_model=config["model_contract"]["requested_model"]
                usage={"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}; cost=0.0
            else:
                global_requests += 1; variant_requests += 1
                try:
                    provider=post_json(model.API_URL,body,api_key)
                    result,response_model,usage=model.parse_provider_response(provider)
                except Exception as exc:
                    isolated.append({"code":code,"reason":"model_failure:"+str(exc)[:80],"source_stage":"MODEL"})
                    global_cost += reserve; variant_cost += reserve
                    continue
                cost=model.usage_peak_cost_cny(usage)
                if cost <= 0: cost=reserve
            global_cost += cost; variant_cost += cost
            for k in global_usage:
                n=int((usage or {}).get(k) or 0); global_usage[k]+=n; variant_usage[k]+=n
            ranked_raw.append(_safe_result(code,result,response_model or config["model_contract"]["requested_model"],usage,feature_hash,cost))
        ranked_raw.sort(key=lambda r:(-r["score"],r["code"]))
        ranked=[dict(r,rank=i+1) for i,r in enumerate(ranked_raw)]
        isolated.sort(key=lambda r:r["code"])
        env=build_ranking_envelope(universe,ranked,isolated,as_of=package_in["decision_at"],claimed_scope="partial_with_isolations" if isolated else "full_pool_complete")
        ranking_sha=canonical_hash([{"code":r["code"],"rank":r["rank"],"score":r["score"],"result_sha256":r["result_sha256"]} for r in ranked])
        payload_sha=canonical_hash({"ranked":ranked,"isolated":isolated,"ranking_envelope":env})
        variant_run=f"{args.run_id}-{variant}"
        generated=datetime.now(timezone.utc).isoformat()
        record={
            "run_id":variant_run,"generated_at":generated,"as_of":package_in["decision_at"],
            "universe_sha256":sha(input_dir/"cohort.json"),"input_sha256":features["input_sha256"],
            "model_version":config["model_contract"]["requested_model"],
            "config_sha256":canonical_hash({"base_config_sha256":sha(config_path),"variant":variant,"omitted_fields":sorted(omitted)}),
            "prediction_payload_sha256":payload_sha,"ranking_sha256":ranking_sha,
            "status":"RUN005_V7_ABLATION_FROZEN_BEFORE_ABLATION_OUTCOME_EVAL",
        }
        ledger_path=freeze_prediction(out/"prediction-ledger",record)
        variants_out[variant]={
            "variant":variant,"omitted_fields":sorted(omitted),"original_denominator":54,
            "ranked_count":len(ranked),"isolated_count":len(isolated),"model_http_requests":variant_requests,
            "ranked":ranked,"isolated":isolated,"ranking_envelope":env,"ranking_sha256":ranking_sha,
            "prediction_payload_sha256":payload_sha,"ledger_file":ledger_path.name,"ledger_file_sha256":sha(ledger_path),
            "usage":variant_usage,"estimated_peak_cny":round(variant_cost,8),"outcome_data_read":False,
        }
    finished=datetime.now(timezone.utc).isoformat()
    package={
        "schema_version":1,"run_id":args.run_id,"status":"RUN005_V7_ABLATION_PREDICTIONS_FROZEN",
        "anchor_id":package_in["anchor_id"],"decision_at":package_in["decision_at"],"original_denominator":54,
        "variant_contract":{k:sorted(v) for k,v in VARIANTS.items()},"variants":variants_out,
        "model_http_requests":global_requests,"usage":global_usage,
        "cost":{"basis":"peak price estimate; not actual invoice","estimated_peak_cny":round(global_cost,8),"actual_cny":None},
        "lineage":{"input_sha256":features["input_sha256"],"pit_manifest_sha256":receipt["manifest_sha256"],"base_config_id":EXPECTED_CONFIG_ID},
        "privacy":{"raw_provider_response_saved":False,"prompt_saved":False,"reasoning_saved":False},
        "outcome_data_read":False,"timing":{"started_at":started,"finished_at":finished},
    }
    (out/"v7-ablation-predictions.json").write_text(json.dumps(package,ensure_ascii=False,indent=2))
    print("RUN005_V7_ABLATION_PREDICTIONS_FROZEN",json.dumps({"variants":5,"denominator":54,"requests":global_requests,"estimated_peak_cny":round(global_cost,8),"ranked_counts":{k:v["ranked_count"] for k,v in variants_out.items()}},separators=(",",":")))
    return package


def parser():
    p=argparse.ArgumentParser(); p.add_argument('--input-dir',required=True); p.add_argument('--config',required=True); p.add_argument('--output',required=True); p.add_argument('--run-id',required=True); p.add_argument('--max-requests',type=int,default=270); p.add_argument('--max-cny',type=float,default=5.0); p.add_argument('--dry-run',action='store_true'); return p

if __name__=='__main__': execute(parser().parse_args())
