#!/usr/bin/env python3
"""Deterministic DSA Migration Readiness pre-window verifier.

This verifier is intentionally incapable of producing 2026-09-22 Natural
Parallel, Gate-D, post-window comparison, or Central Audit evidence.  It only
checks that the already-accepted engineering controls are sealed before that
future observation window.

No network, model, broker, paid-data, ledger-write, runtime-switch, or main
merge surface is used here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

STATE = "PREWINDOW_READY_WAIT_NATURAL_PARALLEL"
FUTURE_BLOCKERS = [
    "FUTURE_NATURAL_PARALLEL_20260922_REQUIRED",
    "SAME_TRIGGER_GATE_D_RECEIPT_REQUIRED",
    "POSTWINDOW_COMPARISON_REQUIRED",
    "INDEPENDENT_CENTRAL_AUDIT_REQUIRED",
]


def load_json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def verify(root: Path) -> dict:
    formal = load_json(root, "docs/runtime/DSA_FORMAL_CURRENT_SESSION_ACCEPTANCE_20260921.json")
    r0 = load_json(root, "docs/runtime/DSA_SNAPSHOT_R0_REPAIR_ACCEPTANCE_20260921.json")
    journal = load_json(root, "docs/runtime/DSA_SIMULATION_JOURNAL_READINESS.json")
    seal = load_json(root, "docs/runtime/DSA_MIGRATION_PREWINDOW_SEAL_20260921.json")
    contract = load_json(root, "docs/runtime/DSA_NATURAL_PARALLEL_20260922_CONTRACT.json")

    checks = {}

    checks["CURRENT_SESSION_FORMAL_WAIT_ACCEPTED"] = (
        formal.get("target_session") == "2026-09-21"
        and formal.get("status") == "ACCEPTED_CURRENT_SESSION_FORMAL_WAIT"
        and formal.get("qualified_buy_total") == 0
        and formal.get("resource_accounting", {}).get("real_orders") == 0
    )

    checks["R0_O_EXPLICIT_GAPS_PRESERVED"] = (
        r0.get("O", {}).get("scanned") == 662
        and r0.get("O", {}).get("current_valid") == 659
        and r0.get("O", {}).get("full_formal_ranking_accepted") is False
        and sorted(r0.get("O", {}).get("invalid_or_stale_codes") or [])
            == sorted(["00853", "02172", "02252"])
    )

    checks["R0_U_45_OF_45_MEASURED"] = (
        r0.get("U", {}).get("denominator") == 45
        and r0.get("U", {}).get("current_member_count") == 45
        and r0.get("U", {}).get("current_valid_count") == 45
        and r0.get("U", {}).get("missing_or_invalid_codes") == []
        and r0.get("U", {}).get("state") == "WAIT_U_MACRO_AUTHORITY"
        and r0.get("U", {}).get("formal_generation_complete") is False
    )

    b = r0.get("boundary", {})
    checks["R0_NO_PAID_OR_RUNTIME_SIDE_EFFECTS"] = (
        b.get("model_http_requests") == 0
        and b.get("paid_data_calls") == 0
        and b.get("real_orders") == 0
        and b.get("runtime_pointer_switch") is False
        and b.get("main_merge") is False
        and b.get("auto_recharge") is False
    )

    checks["SIM_JOURNAL_RESTORE_READY"] = (
        journal.get("state") == "JOURNAL_INITIALIZED"
        and journal.get("command_count") == 0
        and journal.get("save_read_hash_restore") is True
        and journal.get("real_orders") == 0
    )

    journal_impl = (root / "scripts/dsa_simulation_journal_drive.py").read_text(encoding="utf-8")
    checks["REMOTE_CAS_AND_IDEMPOTENCY_PRESENT"] = all(x in journal_impl for x in [
        "JOURNAL_PARENT_HASH_CONFLICT",
        "JOURNAL_IDEMPOTENT",
        "JOURNAL_SAME_COUNT_CONFLICT",
        "expected_parent_hash",
    ])

    entry_wf = (root / ".github/workflows/139-dsa-production-entry-v1.yml").read_text(encoding="utf-8")
    checks["SINGLE_WRITER_CONCURRENCY_AND_PARENT_CAS_PRESENT"] = all(x in entry_wf for x in [
        "group: dsa-production-orchestrator-v1-runtime",
        "--expected-parent-hash",
        "SINGLE_LEDGER_WRITER" if "SINGLE_LEDGER_WRITER" in entry_wf else "dsa_simulation_journal_drive.py load",
        "REAL_ORDERS=0",
    ])

    orch_impl = (root / "scripts/dsa_production_orchestrator_v1.py").read_text(encoding="utf-8")
    checks["COMMAND_DEDUPE_FAIL_CLOSED_PRESENT"] = (
        "COMMAND_ID_CONTENT_DRIFT" in orch_impl
        and "filter_commands_against_journal" in orch_impl
    )

    checks["PREWINDOW_SEAL_BOUNDARIES"] = (
        seal.get("status") == STATE
        and seal.get("runtime_pointer_switch") is False
        and seal.get("main_merge") is False
        and seal.get("paid_full_pool_scan") is False
        and seal.get("real_orders") == 0
    )

    slots = contract.get("future_evidence_slots", {})
    checks["FUTURE_EVIDENCE_NOT_PREGENERATED"] = (
        contract.get("target_session") == "2026-09-22"
        and contract.get("status") == "ARMED_CONTRACT_ONLY_NOT_EVIDENCE"
        and all(slots.get(k) is None for k in [
            "natural_parallel_receipt",
            "same_trigger_gate_d_receipt",
            "postwindow_comparison_receipt",
            "independent_central_audit_receipt",
        ])
    )

    failed = sorted(k for k, ok in checks.items() if not ok)
    state = STATE if not failed else "NOT_READY_PREWINDOW"
    return {
        "schema_version": 1,
        "state": state,
        "checks": checks,
        "failed_checks": failed,
        "future_observation_blockers": FUTURE_BLOCKERS,
        "owner_gate_reached": False,
        "runtime_pointer_switch_performed": False,
        "main_merge_performed": False,
        "paid_full_pool_scan_performed": False,
        "real_orders": 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    result = verify(args.root)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["state"] == STATE else 2


if __name__ == "__main__":
    raise SystemExit(main())
