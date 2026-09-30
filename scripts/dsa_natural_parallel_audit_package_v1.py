#!/usr/bin/env python3
"""Build a deterministic Central Audit package for DSA natural parallel."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT:" + str(path))
    return value


def _fp(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def build_audit_package(
    attestation_path: Path,
    comparison_path: Path,
    active_receipt_path: Path,
    provenance_path: Path,
) -> dict:
    att = _read_json(attestation_path)
    cmp = _read_json(comparison_path)
    active = _read_json(active_receipt_path)
    provenance = _read_json(provenance_path)

    if att.get("status") != "PASS_SAME_CUTOFF_INPUTS":
        raise ValueError("ATTESTATION_NOT_PASS")
    if cmp.get("classification") != "NATURAL_PARALLEL_COMPARISON":
        raise ValueError("COMPARISON_NOT_NATURAL_PARALLEL")
    if cmp.get("natural_parallel_attestation", {}).get("status") != "PASS":
        raise ValueError("COMPARISON_ATTESTATION_NOT_PASS")
    if active.get("shadow_simulation_only") is not True:
        raise ValueError("ACTIVE_RECEIPT_NOT_SHADOW_ONLY")
    if int(active.get("real_orders", 0) or 0) != 0:
        raise ValueError("ACTIVE_RECEIPT_REAL_ORDERS_NONZERO")

    ro = cmp.get("read_only_contract") or {}
    if int(ro.get("authoritative_journal_write_count", -1)) != 0:
        raise ValueError("AUTHORITATIVE_JOURNAL_WRITES_NONZERO")
    if int(ro.get("candidate_journal_write_count", -1)) != 0:
        raise ValueError("CANDIDATE_JOURNAL_WRITES_NONZERO")
    if int(ro.get("real_orders", -1)) != 0:
        raise ValueError("COMPARISON_REAL_ORDERS_NONZERO")

    c = cmp.get("comparison") or {}
    state = str(c.get("migration_acceptance") or "")
    allowed = {
        "ELIGIBLE_FOR_CENTRAL_AUDIT",
        "CENTRAL_AUDIT_REQUIRED_CONTROL_STATE_DIVERGENCE",
        "BLOCKED_ACTION_DIVERGENCE",
    }
    if state not in allowed:
        raise ValueError("MIGRATION_ACCEPTANCE_STATE_INVALID")

    outcome_session = active.get("session")
    expected_session = att.get("next_session")
    if outcome_session != expected_session:
        raise ValueError("OUTCOME_SESSION_MISMATCH")

    sealed_inputs = att.get("input_sha256") or {}
    sealed_journal_sha = sealed_inputs.get("foundation_journal")
    freeze_rows = [
        row for row in (active.get("timeline") or [])
        if isinstance(row, dict) and row.get("stage") == "FREEZE_PRECHECK"
    ]
    if len(freeze_rows) != 1:
        raise ValueError("ACTIVE_FREEZE_PRECHECK_NOT_UNIQUE")
    active_freeze_sha = freeze_rows[0].get("journal_raw_sha256")
    if not sealed_journal_sha or active_freeze_sha != sealed_journal_sha:
        raise ValueError("SEALED_JOURNAL_NOT_EQUAL_ACTIVE_FREEZE")

    if not provenance.get("github_run_id") or not provenance.get("trigger_commit"):
        raise ValueError("TRIGGER_PROVENANCE_INCOMPLETE")

    return {
        "schema_version": 1,
        "package_type": "DSA_NATURAL_PARALLEL_CENTRAL_AUDIT_PACKAGE",
        "status": state,
        "project": "DSA",
        "workstream": "RUNTIME_EXECUTION",
        "target_session": att.get("target_session"),
        "execution_session": expected_session,
        "cutoff_at": att.get("cutoff_at"),
        "sealed_at": att.get("sealed_at"),
        "trade_action_equivalent": bool(c.get("trade_action_equivalent")),
        "control_state_equivalent": bool(c.get("control_state_equivalent")),
        "all_equivalent": bool(c.get("all_equivalent")),
        "safety": {
            "authoritative_journal_writes": 0,
            "candidate_journal_writes": 0,
            "real_orders": 0,
            "runtime_pointer_switch": False,
        },
        "evidence": {
            "attestation": _fp(attestation_path),
            "comparison": _fp(comparison_path),
            "active_runtime_receipt": _fp(active_receipt_path),
            "trigger_provenance": _fp(provenance_path),
            "prewindow_input_sha256": att.get("input_sha256"),
        },
        "trigger_provenance": provenance,
        "pit_crosscheck": {
            "sealed_foundation_journal_sha256": sealed_journal_sha,
            "active_gate_d_freeze_journal_sha256": active_freeze_sha,
            "match": True,
            "external_artifact_timestamp_verification_required": True,
        },
        "central_audit_next": (
            "BLOCK_MIGRATION"
            if state == "BLOCKED_ACTION_DIVERGENCE"
            else "REVIEW_CONTROL_STATE_DIVERGENCE"
            if state == "CENTRAL_AUDIT_REQUIRED_CONTROL_STATE_DIVERGENCE"
            else "INDEPENDENT_CENTRAL_AUDIT"
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attestation", type=Path, required=True)
    ap.add_argument("--comparison", type=Path, required=True)
    ap.add_argument("--active-runtime-receipt", type=Path, required=True)
    ap.add_argument("--provenance", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = build_audit_package(
        args.attestation, args.comparison, args.active_runtime_receipt, args.provenance
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "real_orders": 0, "journal_writes": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
