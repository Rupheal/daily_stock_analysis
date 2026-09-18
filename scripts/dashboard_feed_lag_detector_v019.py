#!/usr/bin/env python3
"""Fail-closed DSA Dashboard feed-lag detector.

Compares the committed v0.19 dashboard feed against a separately checked-out
authoritative runtime branch. No network, model, provider, or secret access.

Exit codes:
  0 ALIGNED
  2 SOURCE_AHEAD
  3 SOURCE_MISMATCH
  4 AUTHORITY_UNAVAILABLE
  5 FEED_INVALID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED_RECEIPT_FIELDS = {
    "official_O_denominator",
    "official_U_denominator",
    "target_session",
    "formal_signal_generated",
}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_number(path: Path) -> int:
    m = re.search(r"RUN(\d+)", path.name)
    return int(m.group(1)) if m else -1


def compatible_receipts(root: Path):
    runtime = root / "docs" / "runtime"
    if not runtime.exists():
        return []
    out = []
    for path in runtime.glob("RUN*_RESULT.json"):
        data = load_json(path)
        if isinstance(data, dict) and REQUIRED_RECEIPT_FIELDS <= set(data):
            out.append((path, data))
    return out


def newest_receipt(root: Path):
    rows = compatible_receipts(root)
    if not rows:
        return None
    rows.sort(
        key=lambda item: (
            str(item[1].get("target_session", "")),
            run_number(item[0]),
            item[0].name,
        )
    )
    return rows[-1]


def normalize_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _metric_receipt(receipt: dict):
    o_den = int(receipt["official_O_denominator"])
    u_den = int(receipt["official_U_denominator"])
    o_invalid = receipt.get("O_current_invalid") or []
    o_ready = int(receipt.get("O_current_valid", o_den - len(o_invalid)))
    u_ready = int(receipt.get("U_current_valid", 0))
    u_buy = int(receipt.get("U_buy_eligible", 0))
    model_requests = int(receipt.get("model_http_requests", 0) or 0)
    model_cost = float(receipt.get("DeepSeek_API_cost_cny", 0) or 0)
    return {
        "O_denominator": o_den,
        "O_data_ready": o_ready,
        "O_data_isolated": o_den - o_ready,
        "U_denominator": u_den,
        "U_data_ready": u_ready,
        "U_data_isolated": u_den - u_ready,
        "U_buy_eligible": u_buy,
        "model_http_requests": model_requests,
        "model_cost_cny": model_cost,
        "formal_signal_generated": bool(receipt.get("formal_signal_generated")),
        "target_session": str(receipt.get("target_session")),
        "run_id": receipt.get("run_id"),
        "workflow_run": receipt.get("source_workflow_run"),
        "artifact_digest": receipt.get("source_artifact_digest"),
    }


def detect(dashboard_root: Path, authority_root: Path, feed_name: str):
    feed_path = dashboard_root / feed_name
    feed = load_json(feed_path)
    if not isinstance(feed, dict):
        return {
            "status": "FEED_INVALID",
            "reason": "feed_missing_or_invalid_json",
            "feed_path": feed_name,
        }, 5

    if feed.get("meta", {}).get("schema_version") != "0.19":
        return {
            "status": "FEED_INVALID",
            "reason": "schema_version_not_0.19",
            "feed_path": feed_name,
        }, 5

    authority = feed.get("authority")
    if not isinstance(authority, dict):
        return {
            "status": "FEED_INVALID",
            "reason": "authority_block_missing",
            "feed_path": feed_name,
        }, 5

    latest = newest_receipt(authority_root)
    if latest is None:
        return {
            "status": "AUTHORITY_UNAVAILABLE",
            "reason": "no_compatible_runtime_receipt",
            "feed_path": feed_name,
        }, 4

    latest_path, latest_receipt = latest
    latest_rel = normalize_rel(latest_path, authority_root)
    latest_sha = sha256_file(latest_path)
    latest_metrics = _metric_receipt(latest_receipt)

    claimed_rel = str(authority.get("source_receipt") or "")
    claimed_sha = str(authority.get("source_receipt_sha256") or "")
    claimed_session = str(authority.get("evidence_session") or "")
    claimed_run = authority.get("source_run_id")

    base = {
        "feed_path": feed_name,
        "feed_generated_at": feed.get("meta", {}).get("generated_at"),
        "feed_source_commit": feed.get("meta", {}).get("source_commit"),
        "claimed": {
            "receipt": claimed_rel,
            "receipt_sha256": claimed_sha,
            "session": claimed_session,
            "run_id": claimed_run,
        },
        "latest_authority": {
            "receipt": latest_rel,
            "receipt_sha256": latest_sha,
            "session": latest_metrics["target_session"],
            "run_id": latest_metrics["run_id"],
            "workflow_run": latest_metrics["workflow_run"],
            "artifact_digest": latest_metrics["artifact_digest"],
        },
    }

    if claimed_rel != latest_rel or claimed_run != latest_metrics["run_id"] or claimed_session != latest_metrics["target_session"]:
        base.update(
            status="SOURCE_AHEAD",
            reason="dashboard_authority_pointer_is_not_latest_compatible_receipt",
        )
        return base, 2

    mismatches = []
    if claimed_sha != latest_sha:
        mismatches.append("source_receipt_sha256")

    checks = {
        "O.denominator": (feed.get("O", {}).get("denominator"), latest_metrics["O_denominator"]),
        "O.data_ready": (feed.get("O", {}).get("data_ready"), latest_metrics["O_data_ready"]),
        "O.data_isolated": (feed.get("O", {}).get("data_isolated"), latest_metrics["O_data_isolated"]),
        "U.denominator": (feed.get("U", {}).get("denominator"), latest_metrics["U_denominator"]),
        "U.data_ready": (feed.get("U", {}).get("data_ready"), latest_metrics["U_data_ready"]),
        "U.data_isolated": (feed.get("U", {}).get("data_isolated"), latest_metrics["U_data_isolated"]),
        "U.buy_eligible": (feed.get("U", {}).get("buy_eligible"), latest_metrics["U_buy_eligible"]),
        "budget.actual_request_count": (
            feed.get("budget", {}).get("actual_request_count"),
            latest_metrics["model_http_requests"],
        ),
        "budget.cost": (feed.get("budget", {}).get("cost"), latest_metrics["model_cost_cny"]),
    }
    for name, (actual, expected) in checks.items():
        if actual != expected:
            mismatches.append(name)

    expected_acceptance = (
        "FORMAL_SIGNAL_GENERATED"
        if latest_metrics["formal_signal_generated"]
        else "NONE_FORMAL_SIGNAL_GENERATED_FALSE"
    )
    if authority.get("strategy_acceptance") != expected_acceptance:
        mismatches.append("authority.strategy_acceptance")

    if mismatches:
        base.update(
            status="SOURCE_MISMATCH",
            reason="dashboard_feed_disagrees_with_claimed_authority_receipt",
            mismatches=mismatches,
        )
        return base, 3

    base.update(
        status="ALIGNED",
        reason="dashboard_feed_matches_latest_compatible_authority_receipt",
        checked_metrics=checks,
    )
    return base, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-root", default=".")
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--feed", default="DSA_DASHBOARD_LIVE_V019.json")
    ap.add_argument("--out")
    args = ap.parse_args()

    report, code = detect(
        Path(args.dashboard_root).resolve(),
        Path(args.authority_root).resolve(),
        args.feed,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
