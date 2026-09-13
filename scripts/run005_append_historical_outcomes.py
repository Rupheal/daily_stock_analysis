"""Append post-freeze historical outcomes to a frozen DSA PIT prediction.

The script is intentionally separate from prediction generation. It reads a frozen
prediction + content-addressed ledger, accepted PIT features, and official HKEX
quotation pages for already-matured horizons. It never mutates the prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from scripts.run004_parse_hkex_pit_quotes import parse_page
from src.services.dsa_prediction_ledger import append_outcome, canonical_hash, load_frozen_prediction

RANDOM_SEED = "TRIDENT-RUN005-RANDOM-V1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hk(code: str) -> str:
    return "HK" + str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def parse_horizon_map(value: str) -> dict[int, str]:
    out = {}
    for item in value.split(","):
        h, date = item.split("=", 1)
        h = int(h)
        if h <= 0 or h in out:
            raise ValueError("invalid_horizon_map")
        out[h] = date
    return dict(sorted(out.items()))


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


def spearman(values_a, values_b):
    return pearson(rank_average(values_a), rank_average(values_b))


def pairwise_accuracy(scores, returns):
    correct = 0; comparable = 0; score_ties = 0; return_ties = 0
    n = len(scores)
    for i in range(n):
        for j in range(i + 1, n):
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
        "accuracy": (correct / comparable) if comparable else None,
    }


def random_score(anchor_id: str, code: str) -> int:
    digest = hashlib.sha256(f"{anchor_id}|{code}|{RANDOM_SEED}".encode()).hexdigest()
    return int(digest, 16)


def verify_inputs(prediction_path: Path, ledger_path: Path, features_path: Path, cohort_path: Path):
    pred = json.loads(prediction_path.read_text())
    ledger, ledger_digest = load_frozen_prediction(ledger_path)
    features = json.loads(features_path.read_text())
    cohort = json.loads(cohort_path.read_text())
    if pred.get("status") != "HISTORICAL_PIT_REPLAY_FROZEN" or pred.get("outcome_data_read") is not False:
        raise ValueError("prediction_not_valid_preoutcome_freeze")
    if ledger.get("status") != "HISTORICAL_PIT_REPLAY_FROZEN_BEFORE_OUTCOME_READ":
        raise ValueError("ledger_status_mismatch")
    if ledger.get("ranking_sha256") != pred.get("hashes", {}).get("ranking_sha256"):
        raise ValueError("ledger_ranking_mismatch")
    if ledger.get("input_sha256") != features.get("input_sha256"):
        raise ValueError("ledger_input_mismatch")
    members = [str(m["code"]).zfill(5) for m in cohort.get("members", [])]
    if [hk(c) for c in members] != sorted([r["code"] for r in pred.get("ranked", [])] + [r["code"] for r in pred.get("isolated", [])]):
        # compare as sets but reject duplicate/count mismatch
        accounted = [r["code"] for r in pred.get("ranked", [])] + [r["code"] for r in pred.get("isolated", [])]
        if len(accounted) != len(set(accounted)) or set(accounted) != {hk(c) for c in members}:
            raise ValueError("prediction_denominator_mismatch")
    fby = {str(r["code"]).zfill(5): r for r in features.get("features", [])}
    if set(fby) != set(members):
        raise ValueError("feature_denominator_mismatch")
    return pred, ledger, ledger_digest, fby, cohort


def execute(args):
    prediction_path = Path(args.prediction)
    ledger_path = Path(args.ledger)
    features_path = Path(args.features)
    cohort_path = Path(args.cohort)
    quote_dir = Path(args.quote_dir)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    pred, ledger, ledger_digest, fby, cohort = verify_inputs(prediction_path, ledger_path, features_path, cohort_path)
    horizons = parse_horizon_map(args.horizons)
    expected = {str(m["code"]).zfill(5): m["english_name"] for m in cohort["members"]}
    anchor_id = args.anchor_id

    outcome_pages = {}
    close_by_horizon = {}
    for horizon, date in horizons.items():
        compact = date.replace("-", "")[2:]
        page = quote_dir / f"d{compact}e.htm"
        if not page.exists():
            raise ValueError(f"missing_outcome_page:{date}")
        parsed = parse_page(page, expected)
        outcome_pages[str(horizon)] = {"date": date, "page_sha256": sha(page)}
        close_by_horizon[horizon] = {code: parsed[code]["closing"] for code in expected}
        if any(v is None for v in close_by_horizon[horizon].values()):
            raise ValueError(f"missing_official_close_h{horizon}")

    score_by = {r["code"]: r["score"] for r in pred["ranked"]}
    rank_by = {r["code"]: r["rank"] for r in pred["ranked"]}
    stance_by = {r["code"]: r["stance"] for r in pred["ranked"]}
    confidence_by = {r["code"]: r["confidence"] for r in pred["ranked"]}
    reason_by = {r["code"]: r["reason_codes"] for r in pred["ranked"]}

    horizon_results = {}
    for horizon, date in horizons.items():
        rows = []
        for raw_code in sorted(expected):
            code = hk(raw_code)
            ref = float(fby[raw_code]["close"])
            close = float(close_by_horizon[horizon][raw_code])
            ret = (close / ref - 1.0) * 100.0
            rows.append({
                "code": code,
                "reference_date": "2026-09-02",
                "reference_close": ref,
                "outcome_date": date,
                "outcome_close": close,
                "forward_return_pct": round(ret, 8),
                "score": score_by[code],
                "rank": rank_by[code],
                "stance": stance_by[code],
                "confidence": confidence_by[code],
                "reason_codes": reason_by[code],
                "predecision_return_20d_pct": fby[raw_code]["return_20d_pct"],
            })
        dsa_scores = [r["score"] for r in rows]
        returns = [r["forward_return_pct"] for r in rows]
        momentum = [r["predecision_return_20d_pct"] for r in rows]
        random_scores = [random_score(anchor_id, r["code"]) for r in rows]
        metrics = {
            "n": len(rows),
            "equal_weight_mean_return_pct": round(sum(returns) / len(returns), 8),
            "dsa_spearman": spearman(dsa_scores, returns),
            "dsa_pairwise": pairwise_accuracy(dsa_scores, returns),
            "momentum_spearman": spearman(momentum, returns),
            "momentum_pairwise": pairwise_accuracy(momentum, returns),
            "random_spearman": spearman(random_scores, returns),
            "random_pairwise": pairwise_accuracy(random_scores, returns),
            "small_cohort_warning": "N<10; do not interpret as full-market efficacy or top-K validation",
        }
        horizon_results[str(horizon)] = {"outcome_date": date, "rows": rows, "metrics": metrics}

    requested_all = [1, 3, 5, 10, 20]
    mature = sorted(horizons)
    waiting = [h for h in requested_all if h not in horizons]
    outcome = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_id": args.outcome_id,
        "status": "PARTIAL_HORIZON_MATURITY" if waiting else "ALL_HORIZONS_MATURE",
        "anchor_id": anchor_id,
        "decision_at": pred["decision_at"],
        "reference_convention": "predecision_last_official_close_to_hth_trading_session_official_close",
        "reference_feature_file_sha256": sha(features_path),
        "metric_contract": args.metric_contract,
        "mature_horizons": mature,
        "wait_maturity_horizons": waiting,
        "outcome_pages": outcome_pages,
        "horizon_results": horizon_results,
        "prediction_ranking_sha256": pred["hashes"]["ranking_sha256"],
        "prediction_payload_sha256": pred["hashes"]["prediction_payload_sha256"],
    }
    linked_path = append_outcome(ledger_path, outcome)
    package = {
        "schema_version": 1,
        "run_id": args.run_id,
        "anchor_id": anchor_id,
        "prediction_sha256": ledger_digest,
        "prediction_file_sha256": sha(prediction_path),
        "ledger_file_sha256": sha(ledger_path),
        "linked_outcome_file": linked_path.name,
        "linked_outcome_file_sha256": sha(linked_path),
        "mature_horizons": mature,
        "wait_maturity_horizons": waiting,
        "horizon_results": horizon_results,
        "outcome_pages": outcome_pages,
        "accepted_progress_claim": "NONE_BY_THIS_ARTIFACT_ALONE",
    }
    package["package_sha256"] = canonical_hash(package)
    (out / "run005-historical-outcome-seed.json").write_text(json.dumps(package, ensure_ascii=False, indent=2))
    # Copy the append-only outcome file into the output directory for artifact retention.
    (out / linked_path.name).write_bytes(linked_path.read_bytes())
    print("RUN005_OUTCOME_SEED_OK", json.dumps({"mature": mature, "waiting": waiting, "prediction_sha256": ledger_digest, "package_sha256": package["package_sha256"]}))
    return package


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--prediction", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--cohort", required=True)
    p.add_argument("--quote-dir", required=True)
    p.add_argument("--horizons", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--anchor-id", required=True)
    p.add_argument("--outcome-id", required=True)
    p.add_argument("--metric-contract", required=True)
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
