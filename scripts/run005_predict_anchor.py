"""Outcome-blind Run005 historical PIT predictor for one frozen SSE anchor.

Consumes only a fail-closed Run005 PIT input package and the already-frozen
RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1 model contract. Members isolated by the
input stage remain in the original denominator and receive no model request.
Only bounded structured model fields are persisted; no raw prompt/response or
reasoning is saved. Post-decision outcome data is never read here.
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

EXPECTED_CONFIG_ID = "RUN004_B3_PRICEONLY_TECHNICAL_SCORER_V1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hk(code: str) -> str:
    return "HK" + str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def load_and_verify(input_dir: Path, config_path: Path):
    package = json.loads((input_dir / "package-manifest.json").read_text())
    features = json.loads((input_dir / "pit-features.json").read_text())
    receipt = json.loads((input_dir / "pit-manifest-receipt.json").read_text())
    cohort = json.loads((input_dir / "cohort.json").read_text())
    coverage = json.loads((input_dir / "coverage.json").read_text())
    config = json.loads(config_path.read_text())

    if package.get("prediction_generated") is not False or package.get("outcome_data_fetched") is not False:
        raise ValueError("input_package_boundary_broken")
    if package.get("pit_input_admissible") is not True:
        raise ValueError("pit_input_package_not_admissible")
    if receipt.get("pit_input_admissible") is not True or receipt.get("prediction_generated") is not False:
        raise ValueError("pit_input_receipt_not_admissible")
    if config.get("config_id") != EXPECTED_CONFIG_ID or config.get("frozen_before_prediction") is not True:
        raise ValueError("model_config_not_frozen")

    decision = package.get("decision_at")
    if not decision or decision != features.get("decision_at") or decision != cohort.get("decision_at") or decision != receipt.get("decision_at"):
        raise ValueError("decision_clock_mismatch")
    anchor_id = package.get("anchor_id")
    if anchor_id != features.get("anchor_id") or anchor_id != cohort.get("anchor_id") or anchor_id != coverage.get("anchor_id"):
        raise ValueError("anchor_id_mismatch")

    members = [str(m["code"]).zfill(5) for m in cohort.get("members", [])]
    if len(members) != package.get("original_denominator") or len(members) != coverage.get("denominator") or len(set(members)) != len(members):
        raise ValueError("original_denominator_mismatch")

    eligible = [str(c).zfill(5) for c in coverage.get("eligible_codes", [])]
    input_isolated = coverage.get("isolated", [])
    isolated_codes = [str(r.get("code")).zfill(5) for r in input_isolated]
    if len(eligible) != package.get("eligible_count") or len(isolated_codes) != package.get("isolated_count"):
        raise ValueError("coverage_count_mismatch")
    if set(eligible) & set(isolated_codes) or set(eligible) | set(isolated_codes) != set(members):
        raise ValueError("coverage_membership_mismatch")

    rows = features.get("features") or []
    feature_codes = [str(r.get("code")).zfill(5) for r in rows]
    if feature_codes != eligible:
        raise ValueError("feature_eligible_order_mismatch")
    for row in rows:
        stored = row.get("feature_sha256")
        projected = {k: v for k, v in row.items() if k != "feature_sha256"}
        if stored != canonical_hash(projected):
            raise ValueError("feature_hash_mismatch:" + str(row.get("code")))

    projected_payload = {k: v for k, v in features.items() if k != "input_sha256"}
    if features.get("input_sha256") != canonical_hash(projected_payload):
        raise ValueError("input_sha256_mismatch")
    if features.get("input_sha256") != package.get("input_sha256"):
        raise ValueError("package_input_hash_mismatch")
    if receipt.get("manifest_sha256") != package.get("manifest_sha256"):
        raise ValueError("manifest_hash_mismatch")

    return package, features, receipt, cohort, coverage, config, members


def execute(args, post_json=model._post_json):
    input_dir = Path(args.input_dir)
    config_path = Path(args.config)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    package_in, features, receipt, cohort, coverage, config, members = load_and_verify(input_dir, config_path)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key and not args.dry_run:
        raise RuntimeError("missing_deepseek_api_key")

    input_isolated = []
    for row in coverage.get("isolated", []):
        input_isolated.append({
            "code": hk(row["code"]),
            "reason": "input_gate:" + str(row.get("reason") or "ISOLATED"),
            "source_stage": "PIT_INPUT",
            "valid_bar_count": row.get("valid_bar_count"),
            "required_bar_count": row.get("required_bar_count"),
        })

    safe_rows = []
    model_isolated = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    estimated_peak_cny = 0.0
    requests = 0
    started = datetime.now(timezone.utc).isoformat()

    for row in features["features"]:
        code = hk(row["code"])
        facts = {k: v for k, v in row.items() if k != "feature_sha256"}
        body = model.request_object(config["model_contract"]["requested_model"], facts)
        reserve = model.conservative_request_reserve_cny(body)
        if requests >= args.max_requests:
            model_isolated.append({"code": code, "reason": "request_limit", "source_stage": "MODEL"})
            continue
        if estimated_peak_cny + reserve > args.max_cny:
            model_isolated.append({"code": code, "reason": "budget_guard", "source_stage": "MODEL"})
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
                model_isolated.append({"code": code, "reason": "model_failure:" + str(exc)[:80], "source_stage": "MODEL"})
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
    isolated = sorted(input_isolated + model_isolated, key=lambda r: r["code"])
    universe = [hk(c) for c in members]
    decision = package_in["decision_at"]
    envelope = build_ranking_envelope(
        universe, ranked, isolated, as_of=decision,
        claimed_scope="partial_with_isolations" if isolated else "full_pool_complete",
    )
    ranking_sha = canonical_hash([{"code": r["code"], "rank": r["rank"], "score": r["score"], "result_sha256": r["result_sha256"]} for r in ranked])
    prediction_payload = {"ranked": ranked, "isolated": isolated, "ranking_envelope": envelope}
    prediction_payload_sha = canonical_hash(prediction_payload)
    finished = datetime.now(timezone.utc).isoformat()

    out_package = {
        "schema_version": 1,
        "run_id": args.run_id,
        "anchor_id": package_in["anchor_id"],
        "status": "HISTORICAL_PIT_REPLAY_FROZEN",
        "decision_at": decision,
        "generated_at": finished,
        "outcome_data_read": False,
        "original_denominator": len(universe),
        "input_eligible_count": package_in["eligible_count"],
        "input_isolated_count": package_in["isolated_count"],
        "ranked_count": len(ranked),
        "model_isolated_count": len(model_isolated),
        "isolated_count": len(isolated),
        "model_http_requests": requests,
        "ranked": ranked,
        "isolated": isolated,
        "ranking_envelope": envelope,
        "usage": usage_total,
        "cost": {"basis": "peak price estimate; not actual invoice", "estimated_peak_cny": round(estimated_peak_cny, 8), "actual_cny": None},
        "hashes": {
            "cohort_sha256": sha(input_dir / "cohort.json"),
            "coverage_sha256": sha(input_dir / "coverage.json"),
            "features_file_sha256": sha(input_dir / "pit-features.json"),
            "pit_receipt_sha256": sha(input_dir / "pit-manifest-receipt.json"),
            "config_file_sha256": sha(config_path),
            "input_sha256": features["input_sha256"],
            "prediction_payload_sha256": prediction_payload_sha,
            "ranking_sha256": ranking_sha,
        },
        "lineage": {"pit_manifest_sha256": receipt.get("manifest_sha256"), "config_id": EXPECTED_CONFIG_ID},
        "privacy": {"raw_provider_response_saved": False, "prompt_saved": False, "reasoning_saved": False},
        "timing": {"started_at": started, "finished_at": finished},
    }
    prediction_file = out / "historical-pit-prediction.json"
    prediction_file.write_text(json.dumps(out_package, ensure_ascii=False, indent=2))

    ledger_record = {
        "run_id": args.run_id,
        "generated_at": finished,
        "as_of": decision,
        "universe_sha256": out_package["hashes"]["cohort_sha256"],
        "input_sha256": features["input_sha256"],
        "model_version": config["model_contract"]["requested_model"],
        "config_sha256": out_package["hashes"]["config_file_sha256"],
        "prediction_payload_sha256": prediction_payload_sha,
        "ranking_sha256": ranking_sha,
        "status": "HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ",
    }
    ledger_path = freeze_prediction(out / "prediction-ledger", ledger_record)
    manifest = {
        "run_id": args.run_id,
        "anchor_id": package_in["anchor_id"],
        "prediction_file_sha256": sha(prediction_file),
        "ledger_file": ledger_path.name,
        "ledger_file_sha256": sha(ledger_path),
        "outcome_data_read": False,
        "original_denominator": len(universe),
        "ranked_count": len(ranked),
        "isolated_count": len(isolated),
        "model_http_requests": requests,
        "estimated_peak_cny": round(estimated_peak_cny, 8),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("RUN005_ANCHOR_PREDICTION_FROZEN", json.dumps({
        "anchor_id": package_in["anchor_id"], "denominator": len(universe), "ranked": len(ranked),
        "input_isolated": len(input_isolated), "model_isolated": len(model_isolated), "requests": requests,
        "estimated_peak_cny": round(estimated_peak_cny, 8), "ranking_sha256": ranking_sha,
    }))
    return out_package


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--max-requests", type=int, required=True)
    p.add_argument("--max-cny", type=float, required=True)
    p.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
