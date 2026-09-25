#!/usr/bin/env python3
"""Seal same-cutoff DSA inputs before a natural parallel runtime window.

This utility does not run the candidate orchestrator and cannot write either
simulation journal. It only fingerprints the three pre-window authority inputs
and emits a time-bound attestation file for later read-only comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

VERSION = "DSA_NATURAL_PARALLEL_PREWINDOW_v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_offset_time(value: str, label: str) -> datetime:
    if not value:
        raise ValueError(label + "_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(label + "_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(label + "_TIMEZONE_REQUIRED")
    return parsed


def seal_inputs(
    o_path: Path,
    u_path: Path,
    foundation_journal_path: Path,
    target_session: str,
    next_session: str,
    cutoff_at: str,
    sealed_at: str | None = None,
) -> dict:
    cutoff = _parse_offset_time(cutoff_at, "PREWINDOW_CUTOFF")
    if sealed_at is None:
        sealed_dt = datetime.now(timezone.utc)
        sealed_at = sealed_dt.isoformat()
    else:
        sealed_dt = _parse_offset_time(sealed_at, "PREWINDOW_SEALED_AT")

    if sealed_dt > cutoff:
        raise ValueError("PREWINDOW_SEAL_AFTER_CUTOFF")

    paths = {
        "o_receipt": o_path,
        "u_receipt": u_path,
        "foundation_journal": foundation_journal_path,
    }
    for key, path in paths.items():
        if not path.is_file():
            raise ValueError("PREWINDOW_INPUT_MISSING:" + key)

    hashes = {key: _sha256(path) for key, path in paths.items()}
    sizes = {key: path.stat().st_size for key, path in paths.items()}
    available = {key: sealed_at for key in paths}

    return {
        "schema_version": 1,
        "version": VERSION,
        "status": "PASS_SAME_CUTOFF_INPUTS",
        "target_session": target_session,
        "next_session": next_session,
        "cutoff_at": cutoff_at,
        "sealed_at": sealed_at,
        "input_available_at": available,
        "input_sha256": hashes,
        "input_bytes": sizes,
        "read_only_contract": {
            "authoritative_foundation_journal_writes": 0,
            "candidate_journal_writes": 0,
            "real_orders": 0,
            "comparison_execution": False,
        },
        "provenance": {
            "seal_clock": "RUNNER_SYSTEM_CLOCK",
            "central_audit_requirement": (
                "Verify this attestation artifact existed in an immutable workflow/commit "
                "record no later than cutoff_at; the JSON alone is not sufficient provenance."
            ),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--o", type=Path, required=True)
    ap.add_argument("--u", type=Path, required=True)
    ap.add_argument("--foundation-journal", type=Path, required=True)
    ap.add_argument("--target-session", required=True)
    ap.add_argument("--next-session", required=True)
    ap.add_argument("--cutoff-at", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    result = seal_inputs(
        args.o,
        args.u,
        args.foundation_journal,
        args.target_session,
        args.next_session,
        args.cutoff_at,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "sealed_at": result["sealed_at"],
        "cutoff_at": result["cutoff_at"],
        "journal_writes": 0,
        "real_orders": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
