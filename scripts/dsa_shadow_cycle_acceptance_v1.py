#!/usr/bin/env python3
"""Deterministic eligibility gate for a genuine DSA Shadow cycle.

This module never calls providers/models/brokers and never grants cycle credit.
It verifies a completed evidence bundle and emits a candidate receipt for an
independent Factory/physical verifier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import exchange_calendars as xcals

CAL = xcals.get_calendar("XHKG")
VERSION = "DSA_SHADOW_CYCLE_ACCEPTANCE_v1"

REQUIRED_EVIDENCE = (
    "O_decision",
    "U_decision",
    "adapter_result",
    "gate_d_receipt",
    "dashboard",
    "runtime_binding",
    "central_audit",
)

def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

def aware(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt

def evidence_ref(root: Path, item: dict, label: str) -> dict:
    if not isinstance(item, dict):
        raise ValueError(f"EVIDENCE_REF_REQUIRED:{label}")
    rel = item.get("path")
    expected = item.get("sha256")
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError(f"EVIDENCE_RELATIVE_PATH_REQUIRED:{label}")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"EVIDENCE_SHA256_REQUIRED:{label}")
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"EVIDENCE_PATH_ESCAPE:{label}") from exc
    raw = path.read_bytes()
    actual = digest_bytes(raw)
    if actual != expected:
        raise ValueError(f"EVIDENCE_HASH_MISMATCH:{label}")
    return {"path": rel, "sha256": actual, "bytes": len(raw)}

def validate(bundle: dict, root: Path) -> dict:
    blockers: list[str] = []
    if bundle.get("schema_version") != 1:
        blockers.append("SCHEMA_VERSION")
    if bundle.get("mode") != "REAL_SHADOW":
        blockers.append("MODE_NOT_REAL_SHADOW")
    if bundle.get("synthetic") is not False:
        blockers.append("SYNTHETIC_NOT_ALLOWED")
    if bundle.get("replay") is not False:
        blockers.append("REPLAY_NOT_ALLOWED")
    if bundle.get("dry_run") is not False:
        blockers.append("DRY_RUN_NOT_ALLOWED")

    target = str(bundle.get("target_session") or "")
    try:
        if not CAL.is_session(target):
            blockers.append("TARGET_NOT_XHKG_SESSION")
    except Exception:
        blockers.append("TARGET_SESSION_INVALID")

    trigger_id = str(bundle.get("trigger_id") or "")
    if not trigger_id:
        blockers.append("TRIGGER_ID_REQUIRED")

    evidence = bundle.get("evidence")
    checked = {}
    if not isinstance(evidence, dict):
        blockers.append("EVIDENCE_MAP_REQUIRED")
        evidence = {}
    for label in REQUIRED_EVIDENCE:
        try:
            checked[label] = evidence_ref(root, evidence.get(label), label)
        except (ValueError, OSError) as exc:
            blockers.append(str(exc))

    tracks = bundle.get("tracks") or {}
    for account in ("O", "U"):
        row = tracks.get(account) if isinstance(tracks, dict) else None
        if not isinstance(row, dict):
            blockers.append(f"{account}_TRACK_REQUIRED")
            continue
        if row.get("target_session") != target:
            blockers.append(f"{account}_SESSION_MISMATCH")
        if row.get("trigger_id") != trigger_id:
            blockers.append(f"{account}_TRIGGER_MISMATCH")
        if row.get("actual_input") is not True:
            blockers.append(f"{account}_ACTUAL_INPUT_REQUIRED")
        if row.get("frozen_version") in (None, ""):
            blockers.append(f"{account}_FROZEN_VERSION_REQUIRED")
        if row.get("state") not in {"WAIT", "QUALIFIED_BUY", "NO_ENTRY_POLICY_BLOCK"}:
            blockers.append(f"{account}_STATE_NOT_ACCEPTABLE")

    journal = bundle.get("journal") or {}
    if not isinstance(journal, dict):
        blockers.append("JOURNAL_REQUIRED")
        journal = {}
    for flag in ("cas_verified", "idempotent_replay_verified", "single_writer_verified"):
        if journal.get(flag) is not True:
            blockers.append(f"JOURNAL_{flag.upper()}_REQUIRED")
    for key in ("parent_hash", "result_hash"):
        value = journal.get(key)
        if not isinstance(value, str) or len(value) != 64:
            blockers.append(f"JOURNAL_{key.upper()}_REQUIRED")
    if type(journal.get("append_count")) is not int or journal.get("append_count") < 0:
        blockers.append("JOURNAL_APPEND_COUNT_INVALID")

    delivery = bundle.get("delivery") or {}
    if not isinstance(delivery, dict):
        blockers.append("DELIVERY_REQUIRED")
        delivery = {}
    if delivery.get("immutable_outputs") is not True:
        blockers.append("IMMUTABLE_OUTPUTS_REQUIRED")
    if delivery.get("dashboard_updated") is not True:
        blockers.append("DASHBOARD_UPDATE_REQUIRED")
    if delivery.get("machine_receipt_written") is not True:
        blockers.append("MACHINE_RECEIPT_REQUIRED")

    scheduler = bundle.get("scheduler") or {}
    if not isinstance(scheduler, dict):
        blockers.append("SCHEDULER_REQUIRED")
        scheduler = {}
    if scheduler.get("eligible_session_schedule_observed") is not True:
        blockers.append("SCHEDULER_OBSERVATION_REQUIRED")
    if scheduler.get("recovery_verified") is not True:
        blockers.append("RECOVERY_EVIDENCE_REQUIRED")

    audit = bundle.get("audit") or {}
    if not isinstance(audit, dict):
        blockers.append("AUDIT_REQUIRED")
        audit = {}
    if audit.get("accepted") is not True:
        blockers.append("CENTRAL_AUDIT_ACCEPTANCE_REQUIRED")
    if audit.get("trigger_id") != trigger_id:
        blockers.append("AUDIT_TRIGGER_MISMATCH")
    if audit.get("target_session") != target:
        blockers.append("AUDIT_SESSION_MISMATCH")

    side = bundle.get("side_effects") or {}
    if not isinstance(side, dict):
        blockers.append("SIDE_EFFECTS_REQUIRED")
        side = {}
    if side.get("candidate_authority_writes") != 0:
        blockers.append("CANDIDATE_AUTHORITY_WRITE_NONZERO")
    if side.get("real_orders") != 0:
        blockers.append("REAL_ORDERS_NONZERO")
    if side.get("production_pointer_switched") is not False:
        blockers.append("PRODUCTION_POINTER_SWITCHED")

    resources = bundle.get("resources") or {}
    if not isinstance(resources, dict):
        blockers.append("RESOURCE_EVIDENCE_REQUIRED")
        resources = {}
    if type(resources.get("paid_requests")) is not int or resources.get("paid_requests") < 0:
        blockers.append("PAID_REQUEST_COUNT_INVALID")
    if resources.get("auto_recharge") is not False:
        blockers.append("AUTO_RECHARGE_NOT_FALSE")

    observed_at = bundle.get("observed_at")
    try:
        aware(observed_at)
    except Exception:
        blockers.append("OBSERVED_AT_INVALID")

    state = "ELIGIBLE_FOR_INDEPENDENT_FACTORY_ACCEPTANCE" if not blockers else "BLOCKED"
    return {
        "schema_version": 1,
        "version": VERSION,
        "cycle_id": bundle.get("cycle_id"),
        "target_session": target,
        "trigger_id": trigger_id,
        "state": state,
        "blockers": sorted(set(blockers)),
        "checked_evidence": checked,
        "natural_cycle_credit": 0,
        "independent_factory_acceptance_required": True,
        "production_activated": False,
        "real_orders": 0,
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = validate(load_json(args.bundle), args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["state"] != "ELIGIBLE_FOR_INDEPENDENT_FACTORY_ACCEPTANCE":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
