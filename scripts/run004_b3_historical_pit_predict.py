"""Execute the precommitted Run004 B3 historical PIT replay.

This runner is deliberately outcome-blind. It accepts only a fail-closed PIT input
receipt plus the precommitted feature/config files, calls the already-authorized
DeepSeek ranking component, persists only bounded structured fields, and freezes an
append-only prediction ledger record. It never fetches or reads post-decision prices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts import run004_pool_safe_deepseek as model
from src.services.dsa_prediction_ledger import canonical_hash, freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope

EXPECTED_DECISION = "2026-09-03T09:00:00+08:00"
EXPECTED_CONFIG_ID = "RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1"
EXPECTED_CODES = ["00100", "02475", "06951"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hk(code: str) -> str:
    return "HK" + str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def load_and_verify(features_path: Path, receipt_path: Path, cohort_path: Path, config_path: Path):
    features = json.loads(features_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    cohort = json.loads(cohort_path.read_text())
    config = json.loads(config_path.read_text())

    if receipt.get("pit_input_admissible") is not True or receipt.get("prediction_generated") is not False:
        raise ValueError("pit_input_receipt_not_admissible")
    if receipt.get("decision_at") != EXPECTED_DECISION:
        raise ValueError("pit_receipt_decision_mismatch")
    if config.get("config_id") != EXPECTED_CONFIG_ID or config.get("decision_at") != EXPECTED_DECISION:
        raise ValueError("precommitted_config_mismatch")
    if config.get("frozen_before_prediction") is not True or config.get("prediction_executed_by_this_file") is not False:
        raise ValueError("config_not_precommitted")
    if config.get("outcome_policy", {}).get("outcome_data_must_not_be_fetched_before_prediction_freeze") is not True:
        raise ValueError("outcome_blindness_not_frozen")
    if cohort.get("decision_at") != EXPECTED_DECISION:
        raise ValueError("cohort_decision_mismatch")
    codes = [str(m["code"]).zfill(5) for m in cohort.get("members", [])]
    if codes != EXPECTED_CODES:
        raise ValueError("cohort_membership_mismatch")
    if features.get("decision_at") != EXPECTED_DECISION or features.get("input_cutoff") != "2026-09-02T23:59:59+08:00":
        raise ValueError("feature_clock_mismatch")
    rows = features.get("features") or []
    if [str(r.get("code")).zfill(5) for r in rows] != EXPECTED_CODES:
        raise ValueError("feature_membership_or_order_mismatch")
    for row in rows:
        stored = row.get("feature_sha256")
        projected = {k: v for k, v in row.items() if k != "feature_sha256"}
        if stored != canonical_hash(projected):
            raise ValueError("feature_hash_mismatch:" + str(row.get("code")))
    # Recompute the input hash exactly as the package builder did before any model call.
    payload = {"decision_at": features["decision_at"], "input_cutoff": features["input_cutoff"], "features": rows}
    stored_input = features.get("input_sha256")
    if stored_input != canonical_hash(payload):
        raise ValueError("pit_input_hash_mismatch")
    return features, receipt, cohort, config


def execute(args, post_json=model._post_json):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    features, receipt, cohort, config = load_and_verify(Path(args.features), Path(args.receipt), Path(args.cohort), Path(args.config))
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key and not args.dry_run:
        raise RuntimeError("missing_deepseek_api_key")

    safe_rows = []
    isolated = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    estimated_peak_cny = 0.0
    requests = 0
    started = datetime.now(timezone.utc).isoformat()
    for row in features["features"]:
        code = hk(row["code"])
        facts = {k: v for k, v in row.items() if k != "feature_sha256"}
        body = model.request_object(config["model_contract"]["requested_model"], facts)
        reserve = model.conservative_request_reserve_cny(body)
        if requests >= args.max_requests or estimated_peak_cny + reserve > args.max_cny:
            isolated.append({"code": code, "reason": "budget_guard"})
            continue
        if args.dry_run:
            result = {"score": 50, "stance": "neutral", "confidence": "low", "reason_codes": ["insufficient_edge"]}
            response_model = config["model_contract"]["requested_model"]
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        else:
            requests += 1
            try:
                provider = post_json(model.API_URL, body, api_key)
                result, response_model, usage = model.parse_provider_response(provider)
            except Exception as exc:
                isolated.append({"code": code, "reason": "model_failure:" + str(exc)[:80]})
                estimated_peak_cny += reserve
                continue
        cost = model.usage_peak_cost_cny(usage)
        if not args.dry_run and cost <= 0:
            cost = reserve
        estimated_peak_cny += cost
        for key in usage_total:
            usage_total[key] += int(usage.get(key) or 0)
        safe = {
            "code": code,
            "score": result["score"],
            "stance": result["stance"],
            "confidence": result["confidence"],
            "reason_codes": result["reason_codes"],
            "feature_sha256": row["feature_sha256"],
            "model": response_model or config["model_contract"]["requested_model"],
            "usage": {k: int(usage.get(k) or 0) for k in usage_total},
            "peak_cost_estimate_cny": round(cost, 8),
        }
        safe["result_sha256"] = canonical_hash({k: safe[k] for k in ("code", "score", "stance", "confidence", "reason_codes", "feature_sha256", "model")})
        safe_rows.append(safe)

    safe_rows.sort(key=lambda r: (-r["score"], r["code"]))
    ranked = [dict(r, rank=i + 1) for i, r in enumerate(safe_rows)]
    isolated.sort(key=lambda r: r["code"])
    universe = [hk(c) for c in EXPECTED_CODES]
    envelope = build_ranking_envelope(
        universe, ranked, isolated, as_of=EXPECTED_DECISION,
        claimed_scope="partial_with_isolations" if isolated else "full_pool_complete",
    )
    ranking_sha = canonical_hash([{"code": r["code"], "rank": r["rank"], "score": r["score"], "result_sha256": r["result_sha256"]} for r in ranked])
    prediction_payload = {"ranked": ranked, "isolated": isolated, "ranking_envelope": envelope}
    prediction_payload_sha = canonical_hash(prediction_payload)
    finished = datetime.now(timezone.utc).isoformat()

    package = {
        "schema_version": 1,
        "run_id": args.run_id,
        "status": "HISTORICAL_PIT_REPLAY_FROZEN",
        "decision_at": EXPECTED_DECISION,
        "generated_at": finished,
        "outcome_data_read": False,
        "denominator": len(universe),
        "ranked_count": len(ranked),
        "isolated_count": len(isolated),
        "model_http_requests": requests,
        "ranked": ranked,
        "isolated": isolated,
        "ranking_envelope": envelope,
        "usage": usage_total,
        "cost": {"basis": "peak price estimate; not actual invoice", "estimated_peak_cny": round(estimated_peak_cny, 8), "actual_cny": None},
        "hashes": {
            "cohort_sha256": sha(Path(args.cohort)),
            "features_file_sha256": sha(Path(args.features)),
            "pit_receipt_sha256": sha(Path(args.receipt)),
            "config_file_sha256": sha(Path(args.config)),
            "input_sha256": features["input_sha256"],
            "prediction_payload_sha256": prediction_payload_sha,
            "ranking_sha256": ranking_sha,
        },
        "lineage": {"pit_manifest_sha256": receipt.get("manifest_sha256"), "config_id": EXPECTED_CONFIG_ID},
        "privacy": {"raw_provider_response_saved": False, "prompt_saved": False, "reasoning_saved": False},
        "timing": {"started_at": started, "finished_at": finished},
    }
    package_path = out / "b3-historical-pit-prediction.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2))

    ledger_record = {
        "run_id": args.run_id,
        "generated_at": finished,
        "as_of": EXPECTED_DECISION,
        "universe_sha256": package["hashes"]["cohort_sha256"],
        "input_sha256": features["input_sha256"],
        "model_version": config["model_contract"]["requested_model"],
        "config_sha256": package["hashes"]["config_file_sha256"],
        "prediction_payload_sha256": prediction_payload_sha,
        "ranking_sha256": ranking_sha,
        "status": "HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ",
    }
    ledger_path = freeze_prediction(out / "prediction-ledger", ledger_record)
    manifest = {
        "run_id": args.run_id,
        "prediction_file_sha256": sha(package_path),
        "ledger_file": ledger_path.name,
        "ledger_file_sha256": sha(ledger_path),
        "outcome_data_read": False,
        "ranked_count": len(ranked),
        "isolated_count": len(isolated),
        "model_http_requests": requests,
        "estimated_peak_cny": round(estimated_peak_cny, 8),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("RUN004_B3_PIT_PREDICTION_FROZEN", json.dumps({"ranked": len(ranked), "isolated": len(isolated), "requests": requests, "estimated_peak_cny": round(estimated_peak_cny, 8), "ranking_sha256": ranking_sha}))
    return package


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--features", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--cohort", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--max-requests", type=int, default=3)
    p.add_argument("--max-cny", type=float, default=1.0)
    p.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
