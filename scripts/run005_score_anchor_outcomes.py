"""Generic append-only Run005 forward-outcome scorer for a frozen historical anchor.

The original prediction denominator is preserved at every matured horizon. Missing
or suspended official closes, input/model isolations, and missing PIT reference
features remain explicit rows. Ranking metrics are computed only on the comparable
subset (frozen rank + PIT reference + valid official outcome), while denominator and
missing-reason counts remain visible. The parent prediction is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scripts.run005_build_anchor_input import parse_partial_page
from src.services.dsa_prediction_ledger import append_outcome, canonical_hash, load_frozen_prediction

RANDOM_SEED = "TRIDENT-RUN005-RANDOM-V1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hk(code: str) -> str:
    return "HK" + str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def parse_horizon_map(value: str) -> dict[int, str]:
    out = {}
    if not value:
        return out
    for item in value.split(","):
        h, date = item.split("=", 1)
        h = int(h)
        if h not in (1, 3, 5, 10, 20) or h in out:
            raise ValueError("invalid_horizon_map")
        out[h] = date
    return dict(sorted(out.items()))


def parse_wait(value: str) -> list[int]:
    if not value:
        return []
    vals = [int(x) for x in value.split(",") if x]
    if len(vals) != len(set(vals)) or any(x not in (1, 3, 5, 10, 20) for x in vals):
        raise ValueError("invalid_wait_horizons")
    return sorted(vals)


def rank_average(values):
    indexed = sorted(enumerate(values), key=lambda x: (x[1], x[0]))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg
        i = j
    return ranks


def pearson(a, b):
    if len(a) != len(b) or len(a) < 2:
        return None
    ma = sum(a) / len(a); mb = sum(b) / len(b)
    da = [x - ma for x in a]; db = [x - mb for x in b]
    den = math.sqrt(sum(x*x for x in da) * sum(x*x for x in db))
    if den == 0:
        return None
    return sum(x*y for x, y in zip(da, db)) / den


def spearman(a, b):
    return pearson(rank_average(a), rank_average(b))


def pairwise(scores, returns):
    correct = comparable = score_ties = return_ties = 0
    for i in range(len(scores)):
        for j in range(i + 1, len(scores)):
            ds = scores[i] - scores[j]; dr = returns[i] - returns[j]
            if ds == 0:
                score_ties += 1; continue
            if dr == 0:
                return_ties += 1; continue
            comparable += 1
            if ds * dr > 0:
                correct += 1
    return {
        "correct_pairs": correct,
        "comparable_pairs": comparable,
        "score_ties": score_ties,
        "return_ties": return_ties,
        "accuracy": correct / comparable if comparable else None,
    }


def random_score(anchor_id, code):
    return int(hashlib.sha256(f"{anchor_id}|{code}|{RANDOM_SEED}".encode()).hexdigest(), 16)


def verify_inputs(prediction_path: Path, ledger_path: Path, input_dir: Path):
    pred = json.loads(prediction_path.read_text())
    ledger, digest = load_frozen_prediction(ledger_path)
    cohort = json.loads((input_dir / "cohort.json").read_text())
    coverage = json.loads((input_dir / "coverage.json").read_text())
    features = json.loads((input_dir / "pit-features.json").read_text())
    package = json.loads((input_dir / "package-manifest.json").read_text())
    if pred.get("status") != "HISTORICAL_PIT_REPLAY_FROZEN" or pred.get("outcome_data_read") is not False:
        raise ValueError("prediction_not_valid_preoutcome_freeze")
    if ledger.get("status") != "HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ":
        raise ValueError("ledger_status_mismatch")
    if ledger.get("ranking_sha256") != pred.get("hashes", {}).get("ranking_sha256"):
        raise ValueError("ledger_ranking_mismatch")
    if ledger.get("input_sha256") != features.get("input_sha256"):
        raise ValueError("ledger_input_mismatch")
    if package.get("prediction_generated") is not False or package.get("outcome_data_fetched") is not False:
        raise ValueError("input_package_boundary_broken")
    if pred.get("anchor_id") != cohort.get("anchor_id") or pred.get("anchor_id") != coverage.get("anchor_id"):
        raise ValueError("anchor_mismatch")
    members = [str(m["code"]).zfill(5) for m in cohort["members"]]
    accounted = [r["code"] for r in pred.get("ranked", [])] + [r["code"] for r in pred.get("isolated", [])]
    if len(accounted) != len(set(accounted)) or set(accounted) != {hk(c) for c in members}:
        raise ValueError("prediction_denominator_mismatch")
    if pred.get("original_denominator") != len(members) or coverage.get("denominator") != len(members):
        raise ValueError("original_denominator_mismatch")
    fby = {str(r["code"]).zfill(5): r for r in features.get("features", [])}
    eligible = {str(c).zfill(5) for c in coverage.get("eligible_codes", [])}
    if set(fby) != eligible:
        raise ValueError("feature_coverage_mismatch")
    return pred, ledger, digest, cohort, coverage, fby, members


def execute(args):
    prediction_path = Path(args.prediction)
    ledger_path = Path(args.ledger)
    input_dir = Path(args.input_dir)
    quote_dir = Path(args.quote_dir)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    pred, ledger, ledger_digest, cohort, coverage, fby, members = verify_inputs(prediction_path, ledger_path, input_dir)
    anchor_id = pred["anchor_id"]
    horizons = parse_horizon_map(args.horizons)
    waiting = parse_wait(args.wait_horizons)
    if set(horizons) & set(waiting) or set(horizons) | set(waiting) != {1,3,5,10,20}:
        raise ValueError("horizon_partition_must_cover_1_3_5_10_20")

    expected = {str(m["code"]).zfill(5): m.get("english_name", "") for m in cohort["members"]}
    pred_ranked = {r["code"]: r for r in pred.get("ranked", [])}
    pred_isolated = {r["code"]: r for r in pred.get("isolated", [])}
    horizon_results = {}
    outcome_pages = {}

    for horizon, date in horizons.items():
        compact = date.replace("-", "")[2:]
        page = quote_dir / f"d{compact}e.htm"
        page_state = "AVAILABLE"
        found = {}; suspended = set(); malformed = set()
        page_hash = None
        if page.exists():
            page_hash = sha(page)
            try:
                found, suspended, malformed = parse_partial_page(page, members)
            except Exception as exc:
                page_state = "UNPARSEABLE:" + type(exc).__name__
        else:
            page_state = "SOURCE_PAGE_MISSING"
        outcome_pages[str(horizon)] = {"date": date, "state": page_state, "page_sha256": page_hash}

        rows = []
        for raw in members:
            code = hk(raw)
            feature = fby.get(raw)
            ranked = pred_ranked.get(code)
            isolated = pred_isolated.get(code)
            status = None; outcome_close = None; forward_return = None
            if page_state != "AVAILABLE":
                status = page_state
            elif raw in suspended:
                status = "SUSPENDED_OR_NO_OFFICIAL_CLOSE"
            elif raw in malformed:
                status = "MALFORMED_OUTCOME_QUOTATION_ROW"
            elif raw not in found:
                status = "OUTCOME_QUOTE_NOT_PRESENT"
            elif found[raw].get("closing") is None:
                status = "SUSPENDED_OR_NO_OFFICIAL_CLOSE"
            else:
                outcome_close = float(found[raw]["closing"])
                if feature is None:
                    status = "NO_PIT_REFERENCE_FEATURE"
                else:
                    ref = float(feature["close"])
                    forward_return = (outcome_close / ref - 1.0) * 100.0
                    status = "VALID_COMPARABLE" if ranked is not None else "VALID_RETURN_PREDICTION_ISOLATED"

            row = {
                "code": code,
                "status": status,
                "prediction_state": "RANKED" if ranked is not None else "ISOLATED",
                "prediction_isolation_reason": isolated.get("reason") if isolated else None,
                "reference_date": feature.get("as_of") if feature else None,
                "reference_close": feature.get("close") if feature else None,
                "outcome_date": date,
                "outcome_close": outcome_close,
                "forward_return_pct": round(forward_return, 8) if forward_return is not None else None,
                "score": ranked.get("score") if ranked else None,
                "rank": ranked.get("rank") if ranked else None,
                "stance": ranked.get("stance") if ranked else None,
                "confidence": ranked.get("confidence") if ranked else None,
                "predecision_return_20d_pct": feature.get("return_20d_pct") if feature else None,
            }
            rows.append(row)

        comparable = [r for r in rows if r["status"] == "VALID_COMPARABLE"]
        valid_returns = [r for r in rows if r["forward_return_pct"] is not None]
        scores = [r["score"] for r in comparable]
        returns = [r["forward_return_pct"] for r in comparable]
        momentum = [r["predecision_return_20d_pct"] for r in comparable]
        random_scores = [random_score(anchor_id, r["code"]) for r in comparable]
        status_counts = dict(sorted(Counter(r["status"] for r in rows).items()))
        k = min(10, max(1, math.ceil(len(comparable) * 0.10))) if comparable else 0
        top_rows = sorted(comparable, key=lambda r: (-r["score"], r["code"]))[:k]
        comp_mean = sum(returns)/len(returns) if returns else None
        top_mean = sum(r["forward_return_pct"] for r in top_rows)/len(top_rows) if top_rows else None
        metrics = {
            "original_matured_denominator": len(members),
            "valid_return_count": len(valid_returns),
            "comparable_ranked_count": len(comparable),
            "noncomparable_count": len(members) - len(comparable),
            "status_counts": status_counts,
            "equal_weight_valid_return_mean_pct": comp_mean,
            "dsa_spearman": spearman(scores, returns),
            "dsa_pairwise": pairwise(scores, returns),
            "momentum_spearman": spearman(momentum, returns),
            "momentum_pairwise": pairwise(momentum, returns),
            "random_spearman": spearman(random_scores, returns),
            "random_pairwise": pairwise(random_scores, returns),
            "top_k": k,
            "top_k_mean_return_pct": top_mean,
            "top_k_lift_vs_comparable_mean_pct": (top_mean - comp_mean) if top_mean is not None and comp_mean is not None else None,
        }
        horizon_results[str(horizon)] = {"outcome_date": date, "rows": rows, "metrics": metrics}

    outcome = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_id": args.outcome_id,
        "status": "PARTIAL_HORIZON_MATURITY" if waiting else "ALL_HORIZONS_MATURE",
        "anchor_id": anchor_id,
        "decision_at": pred["decision_at"],
        "metric_contract": args.metric_contract,
        "mature_horizons": sorted(horizons),
        "wait_maturity_horizons": waiting,
        "original_denominator": len(members),
        "outcome_pages": outcome_pages,
        "horizon_results": horizon_results,
        "prediction_ranking_sha256": pred["hashes"]["ranking_sha256"],
        "prediction_payload_sha256": pred["hashes"]["prediction_payload_sha256"],
    }
    linked = append_outcome(ledger_path, outcome)
    package = {
        "schema_version": 1,
        "run_id": args.run_id,
        "anchor_id": anchor_id,
        "prediction_sha256": ledger_digest,
        "prediction_file_sha256": sha(prediction_path),
        "ledger_file_sha256": sha(ledger_path),
        "linked_outcome_file": linked.name,
        "linked_outcome_file_sha256": sha(linked),
        "mature_horizons": sorted(horizons),
        "wait_maturity_horizons": waiting,
        "original_denominator": len(members),
        "horizon_results": horizon_results,
        "outcome_pages": outcome_pages,
        "accepted_progress_claim": "NONE_BY_THIS_ARTIFACT_ALONE",
    }
    package["package_sha256"] = canonical_hash(package)
    result_path = out / "run005-anchor-outcomes.json"
    result_path.write_text(json.dumps(package, ensure_ascii=False, indent=2))
    (out / linked.name).write_bytes(linked.read_bytes())
    print("RUN005_ANCHOR_OUTCOMES_OK", json.dumps({
        "anchor_id": anchor_id, "denominator": len(members), "mature": sorted(horizons), "waiting": waiting,
        "comparables": {str(h): horizon_results[str(h)]["metrics"]["comparable_ranked_count"] for h in horizons},
        "package_sha256": package["package_sha256"],
    }))
    return package


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--prediction", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--input-dir", required=True)
    p.add_argument("--quote-dir", required=True)
    p.add_argument("--horizons", required=True)
    p.add_argument("--wait-horizons", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--outcome-id", required=True)
    p.add_argument("--metric-contract", required=True)
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
