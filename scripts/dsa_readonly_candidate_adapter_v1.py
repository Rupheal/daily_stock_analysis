#!/usr/bin/env python3
"""Read-only adapter for DSA Production Orchestrator migration comparison.

This adapter is intentionally incapable of writing the authoritative simulation
journal. It reads:
- current formal O receipt;
- current formal U receipt;
- current Foundation journal snapshot;
- current active runtime receipt.

It then runs the candidate orchestrator in-memory and emits only a comparison
receipt. Natural-parallel acceptance is impossible without an explicit,
hash-bound same-cutoff input attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from dsa_production_orchestrator_v1 import (
    filter_commands_against_journal,
    orchestrate,
)

VERSION = "DSA_READONLY_CANDIDATE_ADAPTER_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT:" + str(path))
    return value


def _fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "sha256": _sha256(data), "bytes": len(data)}


def validate_journal(journal: dict) -> dict:
    config_hash = str(journal.get("config_hash") or "")
    if not SHA256_RE.fullmatch(config_hash):
        raise ValueError("FOUNDATION_JOURNAL_CONFIG_HASH_INVALID")
    commands = journal.get("commands")
    if not isinstance(commands, list):
        raise ValueError("FOUNDATION_JOURNAL_COMMANDS_INVALID")

    parent = config_hash
    last_hash = config_hash
    for index, wrapper in enumerate(commands):
        if not isinstance(wrapper, dict):
            raise ValueError(f"FOUNDATION_JOURNAL_WRAPPER_INVALID:{index}")
        if wrapper.get("parent") != parent:
            raise ValueError(f"FOUNDATION_JOURNAL_PARENT_CHAIN_INVALID:{index}")
        command = wrapper.get("command")
        if not isinstance(command, dict) or not command.get("id"):
            raise ValueError(f"FOUNDATION_JOURNAL_COMMAND_INVALID:{index}")
        current_hash = str(wrapper.get("hash") or "")
        if not SHA256_RE.fullmatch(current_hash):
            raise ValueError(f"FOUNDATION_JOURNAL_HASH_INVALID:{index}")
        parent = current_hash
        last_hash = current_hash

    return {
        "config_hash": config_hash,
        "command_count": len(commands),
        "tail_hash": last_hash,
    }


def _active_trade_outcome(receipt: dict) -> dict:
    if int(receipt.get("real_orders", 0) or 0) != 0:
        raise ValueError("ACTIVE_RECEIPT_REAL_ORDER_NONZERO")
    if receipt.get("shadow_simulation_only") is not True:
        raise ValueError("ACTIVE_RECEIPT_NOT_SHADOW_ONLY")

    buys = 0
    positions = 0
    for account in ("O", "U"):
        block = receipt.get(account) or {}
        buys += int(block.get("buy_count", 0) or 0)
        positions += int(block.get("positions", 0) or 0)

    return {
        "trade_action": "SIMULATED_ENTRY_OR_POSITION" if buys or positions else "NO_TRADE",
        "buy_count": buys,
        "positions": positions,
        "fail_closed": bool(receipt.get("fail_closed")),
    }


def _candidate_trade_outcome(candidate: dict) -> dict:
    entries = [x for x in candidate.get("commands", []) if x.get("kind") == "ENTRY"]
    return {
        "trade_action": "ENTRY_CANDIDATE" if entries else "NO_TRADE",
        "entry_count": len(entries),
        "control_state": candidate.get("state"),
        "qualified_buy_total": int(candidate.get("qualified_buy_total", 0) or 0),
    }


def _validate_natural_attestation(attestation: dict, target_session: str, fps: dict) -> dict:
    if not isinstance(attestation, dict):
        raise ValueError("NATURAL_PARALLEL_ATTESTATION_REQUIRED")
    if attestation.get("status") != "PASS_SAME_CUTOFF_INPUTS":
        raise ValueError("NATURAL_PARALLEL_ATTESTATION_NOT_PASS")
    if attestation.get("target_session") != target_session:
        raise ValueError("NATURAL_PARALLEL_SESSION_MISMATCH")
    expected = attestation.get("input_sha256")
    if not isinstance(expected, dict):
        raise ValueError("NATURAL_PARALLEL_INPUT_HASHES_MISSING")
    for key, fp in fps.items():
        if expected.get(key) != fp["sha256"]:
            raise ValueError("NATURAL_PARALLEL_INPUT_HASH_MISMATCH:" + key)
    cutoff = attestation.get("cutoff_at")
    if not isinstance(cutoff, str) or not cutoff:
        raise ValueError("NATURAL_PARALLEL_CUTOFF_MISSING")
    return {"status": "PASS", "cutoff_at": cutoff}


def compare_read_only(
    o_path: Path,
    u_path: Path,
    foundation_journal_path: Path,
    active_receipt_path: Path,
    target_session: str,
    now_iso: str,
    next_session: str,
    cycle: str = "preopen",
    entry_evidence_path: Path | None = None,
    comparison_kind: str = "engineering_replay",
    availability_attestation_path: Path | None = None,
) -> dict:
    fps = {
        "o_receipt": _fingerprint(o_path),
        "u_receipt": _fingerprint(u_path),
        "foundation_journal": _fingerprint(foundation_journal_path),
        "active_runtime_receipt": _fingerprint(active_receipt_path),
    }
    journal_before = foundation_journal_path.read_bytes()
    journal = _read_json(foundation_journal_path)
    journal_state = validate_journal(journal)
    active_receipt = _read_json(active_receipt_path)
    o_receipt = _read_json(o_path)
    u_receipt = _read_json(u_path)
    entry = _read_json(entry_evidence_path) if entry_evidence_path else None

    if comparison_kind not in {"engineering_replay", "natural_parallel"}:
        raise ValueError("COMPARISON_KIND_INVALID")

    attestation_result = None
    if comparison_kind == "natural_parallel":
        if availability_attestation_path is None:
            raise ValueError("NATURAL_PARALLEL_ATTESTATION_REQUIRED")
        attestation_result = _validate_natural_attestation(
            _read_json(availability_attestation_path), target_session, fps
        )

    candidate = orchestrate(
        o_receipt,
        u_receipt,
        target_session,
        now_iso,
        next_session,
        o_path,
        u_path,
        entry,
        True,
        cycle,
    )
    pending, noop = filter_commands_against_journal(candidate.get("commands", []), journal)

    journal_after = foundation_journal_path.read_bytes()
    if journal_before != journal_after:
        raise RuntimeError("READ_ONLY_VIOLATION_FOUNDATION_JOURNAL_MUTATED")

    active_outcome = _active_trade_outcome(active_receipt)
    candidate_outcome = _candidate_trade_outcome(candidate)
    action_equivalent = (
        active_outcome["trade_action"] == "NO_TRADE"
        and candidate_outcome["trade_action"] == "NO_TRADE"
    )

    active_state = (
        "NO_TRADE_FAIL_CLOSED"
        if active_outcome["trade_action"] == "NO_TRADE" and active_outcome["fail_closed"]
        else active_outcome["trade_action"]
    )
    control_state_equivalent = candidate_outcome["control_state"] == active_state

    classification = (
        "NATURAL_PARALLEL_COMPARISON"
        if comparison_kind == "natural_parallel"
        else "ENGINEERING_REPLAY_NOT_NATURAL_PARALLEL"
    )

    return {
        "schema_version": 1,
        "version": VERSION,
        "classification": classification,
        "target_session": target_session,
        "generated_at": now_iso,
        "cycle": cycle,
        "read_only_contract": {
            "authoritative_journal_write_count": 0,
            "candidate_journal_write_count": 0,
            "real_orders": 0,
            "foundation_journal_unchanged": True,
            "comparison_receipt_only": True,
        },
        "inputs": fps,
        "foundation_journal": journal_state,
        "candidate": {
            "control_state": candidate_outcome["control_state"],
            "trade_action": candidate_outcome["trade_action"],
            "qualified_buy_total": candidate_outcome["qualified_buy_total"],
            "entry_count": candidate_outcome["entry_count"],
            "would_emit_command_count": len(candidate.get("commands", [])),
            "would_append_command_count": len(pending),
            "idempotent_noop_command_count": len(noop),
            "would_emit_command_ids": [str(x.get("id") or "") for x in candidate.get("commands", [])],
            "O_state": (candidate.get("tracks") or {}).get("O", {}).get("state"),
            "U_state": (candidate.get("tracks") or {}).get("U", {}).get("state"),
        },
        "active": {
            "trade_action": active_outcome["trade_action"],
            "buy_count": active_outcome["buy_count"],
            "positions": active_outcome["positions"],
            "fail_closed": active_outcome["fail_closed"],
            "derived_control_state": active_state,
        },
        "comparison": {
            "trade_action_equivalent": action_equivalent,
            "control_state_equivalent": control_state_equivalent,
            "migration_acceptance": (
                "ELIGIBLE_FOR_CENTRAL_AUDIT"
                if comparison_kind == "natural_parallel" and action_equivalent
                else "NOT_ELIGIBLE_ENGINEERING_ONLY"
            ),
        },
        "natural_parallel_attestation": attestation_result,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--o", type=Path, required=True)
    ap.add_argument("--u", type=Path, required=True)
    ap.add_argument("--foundation-journal", type=Path, required=True)
    ap.add_argument("--active-runtime-receipt", type=Path, required=True)
    ap.add_argument("--target-session", required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--next-session", required=True)
    ap.add_argument("--cycle", choices=["preopen", "postclose"], default="preopen")
    ap.add_argument("--entry-evidence", type=Path)
    ap.add_argument(
        "--comparison-kind",
        choices=["engineering_replay", "natural_parallel"],
        default="engineering_replay",
    )
    ap.add_argument("--availability-attestation", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    result = compare_read_only(
        args.o,
        args.u,
        args.foundation_journal,
        args.active_runtime_receipt,
        args.target_session,
        args.now,
        args.next_session,
        args.cycle,
        args.entry_evidence,
        args.comparison_kind,
        args.availability_attestation,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "classification": result["classification"],
        "candidate_state": result["candidate"]["control_state"],
        "candidate_trade_action": result["candidate"]["trade_action"],
        "active_trade_action": result["active"]["trade_action"],
        "trade_action_equivalent": result["comparison"]["trade_action_equivalent"],
        "control_state_equivalent": result["comparison"]["control_state_equivalent"],
        "journal_writes": 0,
        "real_orders": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
