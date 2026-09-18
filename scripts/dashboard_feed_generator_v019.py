#!/usr/bin/env python3
"""DSA Dashboard v0.19 canonical-feed generator.

Model-free and network-free. It discovers the newest compatible runtime receipt,
preserves the distinction between data readiness and formal strategy acceptance,
and emits one sanitized canonical feed plus append-only daily telemetry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

BRANCH = "research/dsa-dashboard-v019-20260918"
SECRET_RE = re.compile(r"(?i)(api[_-]?key|client_secret|refresh_token|authorization|bearer\s+\S+)")

def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

def run_number(path: Path) -> int:
    m = re.search(r"RUN(\d+)", path.name)
    return int(m.group(1)) if m else -1

def compatible_receipts(root: Path):
    for path in (root / "docs" / "runtime").glob("RUN*_RESULT.json"):
        data = load(path, {}) or {}
        required = {"official_O_denominator", "official_U_denominator", "target_session", "formal_signal_generated"}
        if required <= set(data):
            yield path, data

def choose_latest(root: Path):
    rows = list(compatible_receipts(root))
    if not rows:
        raise SystemExit("no compatible current-session runtime receipt")
    rows.sort(key=lambda x: (str(x[1].get("target_session", "")), run_number(x[0]), x[0].name))
    return rows[-1]

def build_feed(root: Path, source_commit: str, generated_at: str | None = None) -> dict:
    path, r = choose_latest(root)
    now = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    o_den = int(r["official_O_denominator"])
    u_den = int(r["official_U_denominator"])
    if u_den != 45:
        raise SystemExit("U denominator invariant failed")
    o_invalid = r.get("O_current_invalid") or []
    o_ready = int(r.get("O_current_valid", o_den - len(o_invalid)))
    u_ready = int(r.get("U_current_valid", 0))
    buy_eligible = int(r.get("U_buy_eligible", 0))
    formal = bool(r.get("formal_signal_generated"))
    model_requests = int(r.get("model_http_requests", 0) or 0)
    cost = float(r.get("DeepSeek_API_cost_cny", 0) or 0)
    next_action = r.get("next") or "Run the next deterministic model-free gate."
    session = str(r["target_session"])
    feed = {
        "meta": {
            "schema_version": "0.19",
            "generated_at": now,
            "source_commit": source_commit,
            "branch": BRANCH,
            "latest_validated_run": r.get("run_id"),
            "evidence_timestamp": r.get("evidence_timestamp") or now,
        },
        "authority": {
            "canonical_feed_path": "DSA_DASHBOARD_LIVE_V019.json",
            "source_receipt": str(path.relative_to(root)).replace("\\", "/"),
            "source_receipt_sha256": sha256_file(path),
            "source_run_id": r.get("run_id"),
            "source_workflow_run": r.get("source_workflow_run"),
            "source_artifact_digest": r.get("source_artifact_digest"),
            "evidence_session": session,
            "evidence_class": "CURRENT_SESSION_CORE_DATA_REFRESH",
            "strategy_acceptance": "FORMAL_SIGNAL_GENERATED" if formal else "NONE_FORMAL_SIGNAL_GENERATED_FALSE",
        },
        "system": {
            "overall_state": "LIVE" if formal else "WAIT",
            "current_stage": "FORMAL_SIGNAL_AVAILABLE" if formal else "CURRENT_SESSION_SENTINEL_PREFLIGHT_PENDING",
            "next_action": next_action,
            "last_successful_gate": "CORE_DATA_REFRESH_PASS",
            "blocking_gate": None if formal else "CURRENT_SESSION_SENTINEL_PREFLIGHT_PENDING",
            "error_code": None,
        },
        "O": {
            "denominator": o_den,
            "data_ready": o_ready,
            "data_isolated": o_den - o_ready,
            "attempted": 0,
            "accepted": 0,
            "top3": [],
            "signal": "WAIT" if not formal else "NOT_VERIFIED",
            "qualified_buy": False,
            "latest_session": session,
            "model_http_requests": model_requests,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_or_actual_cost": cost,
            "evidence_status": "CORE_DATA_REFRESH_PASS; FORMAL_SIGNAL_" + ("GENERATED" if formal else "NOT_GENERATED"),
        },
        "U": {
            "denominator": u_den,
            "data_ready": u_ready,
            "data_isolated": u_den - u_ready,
            "buy_eligible": buy_eligible,
            "attempted": 0,
            "accepted": 0,
            "top3": [],
            "signal": "WAIT" if not formal else "NOT_VERIFIED",
            "qualified_buy": False,
            "evidence_status": "CORE_DATA_REFRESH_PASS; FORMAL_SIGNAL_" + ("GENERATED" if formal else "NOT_GENERATED"),
        },
        "data_health": {
            "fresh_preflight": "PENDING_ZERO_MODEL_SENTINEL_PREFLIGHT" if not formal else "PASS",
            "provider": "CORE_DATA_REFRESH_PASS",
            "session": "PASS:" + session,
            "OHLC": f"O{o_ready}/{o_den}; U{u_ready}/{u_den} CURRENT",
            "volume": "MARKET_HISTORY_HASH_FROZEN; SENTINEL_RECHECK_PENDING" if not formal else "PASS",
            "news": "NOT_VERIFIED_BY_CURRENT_CORE_REFRESH",
            "issuer": "NOT_VERIFIED_BY_CURRENT_CORE_REFRESH",
            "manifest": "CURRENT_SESSION_IMMUTABLE_INPUT_READY",
        },
        "observer": {
            "pass_fail": "NOT_RUN_AFTER_CURRENT_CORE_REFRESH" if not formal else "NOT_VERIFIED",
            "block_count": 0,
            "latest_error_code": None,
        },
        "storage": {
            "save": "SOURCE_ARTIFACT_RECOVERED",
            "independent_read": "SOURCE_ARTIFACT_DIGEST_RECORDED",
            "sha_match": "SOURCE_ARTIFACT_DIGEST_RECORDED",
            "revision_check": source_commit[:12],
            "restore_verified": "NOT_EVALUATED_CURRENT_CYCLE",
            "source_artifact_digest_verified": "RECORDED_FROM_WORKFLOW_ARTIFACT",
        },
        "budget": {
            "affordability": "NO_MODEL_REQUEST_REQUIRED_FOR_NEXT_SENTINEL",
            "request_limit": model_requests,
            "actual_request_count": model_requests,
            "tokens": {"input": 0, "output": 0, "total": 0},
            "cost": cost,
        },
        "simulation": {
            "eligibility": "WAIT_NOT_ELIGIBLE_NO_FORMAL_SIGNAL" if not formal else "NOT_VERIFIED",
            "account_A": "NOT_VERIFIED",
            "account_B": "NOT_VERIFIED",
            "cash": "NOT_VERIFIED",
            "positions": "NOT_VERIFIED",
            "pnl": "NOT_VERIFIED",
            "pending_signal": "WAIT" if not formal else "NOT_VERIFIED",
        },
        "shadow_week": {
            "date": session,
            "data_pass_rate": "CORE_REFRESH_PASS_SENTINEL_PENDING" if not formal else "PASS",
            "observer_block_rate": "NOT_RUN_AFTER_CURRENT_CORE_REFRESH" if not formal else "NOT_VERIFIED",
            "model_success_rate": "NOT_APPLICABLE_NO_MODEL_CALL" if model_requests == 0 else "NOT_VERIFIED",
            "cost_per_accepted_analysis": "NOT_APPLICABLE" if model_requests == 0 else "NOT_VERIFIED",
            "O_coverage": f"data {o_ready}/{o_den}; formal 0/{o_den}",
            "U_coverage": f"data {u_ready}/{u_den}; buy-eligible {buy_eligible}/{u_den}; formal 0/{u_den}",
            "top3_turnover": "NOT_VERIFIED",
            "signal_persistence": "WAIT" if not formal else "NOT_VERIFIED",
            "BUY_WAIT": "WAIT" if not formal else "NOT_VERIFIED",
            "simulation_eligibility": "WAIT_NOT_ELIGIBLE_NO_FORMAL_SIGNAL" if not formal else "NOT_VERIFIED",
        },
        "debug": {
            "provider_error": None,
            "preflight_error": None if formal else "CURRENT_SESSION_SENTINEL_PREFLIGHT_PENDING",
            "observer_error": "NOT_RUN_AFTER_CURRENT_CORE_REFRESH" if not formal else None,
            "drive_error": None,
            "model_error": None,
            "recovery_state": r.get("state"),
            "recovery_condition": next_action,
            "O_invalid": o_invalid,
        },
    }
    encoded = json.dumps(feed, ensure_ascii=False)
    if SECRET_RE.search(encoded):
        raise SystemExit("sanitized feed failed secret scan")
    if feed["O"]["data_ready"] + feed["O"]["data_isolated"] != o_den:
        raise SystemExit("O coverage invariant failed")
    if feed["U"]["data_ready"] + feed["U"]["data_isolated"] != u_den:
        raise SystemExit("U coverage invariant failed")
    return feed

def append_history(path: Path, feed: dict):
    history = load(path, {"schema_version": "0.19", "append_only": True, "days": []})
    days = history.setdefault("days", [])
    d = dict(feed["shadow_week"])
    d.update(
        latest_validated_run=feed["meta"]["latest_validated_run"],
        model_requests=feed["budget"]["actual_request_count"],
        input_tokens=feed["budget"]["tokens"]["input"],
        output_tokens=feed["budget"]["tokens"]["output"],
        total_tokens=feed["budget"]["tokens"]["total"],
        cost=feed["budget"]["cost"],
        blocking_gate=feed["system"]["blocking_gate"],
        authority_receipt=feed["authority"]["source_receipt"],
    )
    if d["date"] not in {x.get("date") for x in days}:
        days.append(d)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="DSA_DASHBOARD_LIVE_V019.json")
    ap.add_argument("--history", default="DSA_DASHBOARD_HISTORY_V019.json")
    ap.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    ap.add_argument("--generated-at")
    args = ap.parse_args()
    root = Path(args.root)
    feed = build_feed(root, args.source_commit, args.generated_at)
    Path(args.out).write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_history(Path(args.history), feed)

if __name__ == "__main__":
    main()
