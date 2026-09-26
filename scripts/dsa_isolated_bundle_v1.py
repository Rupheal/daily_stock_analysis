#!/usr/bin/env python3
"""Build a fail-closed isolated DSA bundle without touching Production authority.

This wrapper composes the existing Resolver -> Orchestrator -> Entry-v1 -> isolated
journal replay path. It never initializes a journal, never mutates the supplied
journal, never grants natural-cycle credit, and never switches Production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from scripts.dsa_formal_receipt_resolver_v1 import resolve
from scripts.dsa_production_orchestrator_v1 import orchestrate
from scripts.dsa_isolated_entry_replay_v1 import replay_candidate
from src.services.dsa_prediction_ledger import canonical_hash

VERSION = "DSA_ISOLATED_BUNDLE_v1"
CLASSIFICATIONS = {"REAL", "SYNTHETIC", "HISTORICAL_REPLAY"}
REPLAYABLE_STATES = {"READY_FOR_ENTRY_V1_REPLAY", "WAIT_NO_BUY"}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def aware(value: str, label: str) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}_INVALID") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{label}_NAIVE")
    return dt.isoformat()


def commit_sha(value: str) -> str:
    value = str(value or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("CODE_SHA_INVALID")
    return value


def file_identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": digest_bytes(raw),
        "bytes": len(raw),
    }


def write_once(path: Path, value: object) -> dict:
    raw = json_bytes(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"OUTPUT_DRIFT:{path.name}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"sha256": digest_bytes(raw), "bytes": len(raw)}


def resolved_track(resolved: dict, account: str) -> dict:
    row = resolved.get(account) if isinstance(resolved, dict) else None
    row = row if isinstance(row, dict) else {}
    receipt = row.get("receipt")
    path_value = row.get("path")
    result = {
        "account": account,
        "available": isinstance(receipt, dict) and bool(path_value),
        "path": str(path_value) if path_value else None,
        "target_session": receipt.get("target_session") if isinstance(receipt, dict) else None,
        "status": (
            receipt.get("status")
            if account == "O" and isinstance(receipt, dict)
            else receipt.get("state") if isinstance(receipt, dict) else None
        ),
        "checked": row.get("checked") if isinstance(row.get("checked"), list) else [],
    }
    if result["available"]:
        source = Path(str(path_value))
        if not source.exists():
            raise ValueError(f"{account}_RESOLVED_SOURCE_MISSING")
        raw = source.read_bytes()
        parsed = json.loads(raw)
        if parsed != receipt:
            raise ValueError(f"{account}_RESOLVED_SOURCE_CONTENT_MISMATCH")
        result["sha256"] = digest_bytes(raw)
        result["bytes"] = len(raw)
    else:
        result["sha256"] = None
        result["bytes"] = None
    return result


def make_spec(
    *,
    run_id: str,
    target_session: str,
    now: str,
    next_session: str,
    verification_clock: str,
    code_sha: str,
    input_classification: str,
    entry_path: Path,
    journal_path: Path,
    expected_blob: str,
    expected_hash: str,
    resolved: dict,
) -> dict:
    classification = str(input_classification or "").upper()
    if classification not in CLASSIFICATIONS:
        raise ValueError("INPUT_CLASSIFICATION_INVALID")
    if not run_id:
        raise ValueError("RUN_ID_REQUIRED")
    entry = file_identity(entry_path)
    journal_raw = journal_path.read_bytes()
    journal = json.loads(journal_raw)
    if git_blob_sha(journal_raw) != expected_blob:
        raise ValueError("JOURNAL_GIT_BLOB_MISMATCH")
    if canonical_hash(journal) != expected_hash:
        raise ValueError("JOURNAL_CANONICAL_HASH_MISMATCH")
    tracks = {account: resolved_track(resolved, account) for account in ("O", "U")}
    bundle_script = file_identity(Path(__file__))
    return {
        "schema_version": 1,
        "version": VERSION,
        "run_id": run_id,
        "target_session": target_session,
        "now": aware(now, "NOW"),
        "next_session": next_session,
        "verification_clock": aware(verification_clock, "VERIFICATION_CLOCK"),
        "code_sha": commit_sha(code_sha),
        "bundle_script_sha256": bundle_script["sha256"],
        "input_classification": classification,
        "entry_evidence": entry,
        "journal": {
            "path": str(journal_path),
            "file_sha256": digest_bytes(journal_raw),
            "git_blob_sha1": expected_blob,
            "canonical_hash": expected_hash,
            "bytes": len(journal_raw),
        },
        "tracks": tracks,
    }


def verify_complete(out_dir: Path, expected_spec_hash: str) -> dict:
    manifest_path = out_dir / "manifest.json"
    receipt_path = out_dir / "bundle-receipt.json"
    if not manifest_path.is_file() or not receipt_path.is_file():
        raise ValueError("COMPLETE_OUTPUT_MARKERS_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != VERSION:
        raise ValueError("MANIFEST_VERSION_MISMATCH")
    if manifest.get("spec_sha256") != expected_spec_hash:
        raise ValueError("SPEC_HASH_MISMATCH")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("MANIFEST_FILES_INVALID")
    for name, meta in files.items():
        path = out_dir / name
        if not path.is_file():
            raise ValueError(f"OUTPUT_FILE_MISSING:{name}")
        raw = path.read_bytes()
        if (
            not isinstance(meta, dict)
            or meta.get("sha256") != digest_bytes(raw)
            or meta.get("bytes") != len(raw)
        ):
            raise ValueError(f"OUTPUT_HASH_MISMATCH:{name}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("spec_sha256") != expected_spec_hash:
        raise ValueError("RECEIPT_SPEC_HASH_MISMATCH")
    return receipt


def build_bundle(
    *,
    root: Path,
    target_session: str,
    now: str,
    next_session: str,
    verification_clock: str,
    entry_evidence: Path,
    journal: Path,
    expected_blob: str,
    expected_hash: str,
    out_dir: Path,
    run_id: str,
    code_sha: str,
    input_classification: str,
    resolver: Callable = resolve,
    orchestrator: Callable = orchestrate,
    replayer: Callable = replay_candidate,
) -> dict:
    raw_before = journal.read_bytes()
    if git_blob_sha(raw_before) != expected_blob:
        raise ValueError("JOURNAL_GIT_BLOB_MISMATCH")
    journal_value = json.loads(raw_before)
    if canonical_hash(journal_value) != expected_hash:
        raise ValueError("JOURNAL_CANONICAL_HASH_MISMATCH")
    replayer(raw_before, expected_blob, expected_hash, [])
    resolved = resolver(root, target_session)
    spec = make_spec(
        run_id=run_id,
        target_session=target_session,
        now=now,
        next_session=next_session,
        verification_clock=verification_clock,
        code_sha=code_sha,
        input_classification=input_classification,
        entry_path=entry_evidence,
        journal_path=journal,
        expected_blob=expected_blob,
        expected_hash=expected_hash,
        resolved=resolved,
    )
    spec_raw = json_bytes(spec)
    spec_hash = digest_bytes(spec_raw)

    if out_dir.exists():
        receipt = verify_complete(out_dir, spec_hash)
        result = dict(receipt)
        result["delivery_noop"] = True
        return result

    partial = out_dir.with_name(out_dir.name + ".partial")
    partial.mkdir(parents=True, exist_ok=True)
    spec_meta = write_once(partial / "bundle-spec.json", spec)
    if spec_meta["sha256"] != spec_hash:
        raise AssertionError("SPEC_HASH_INTERNAL_MISMATCH")
    write_once(partial / "resolver.json", resolved)

    tracks = spec["tracks"]
    state = "BLOCKED_INPUTS"
    replayed = None
    orchestration = None

    if resolved.get("state") == "READY" and all(
        tracks[account]["available"] for account in ("O", "U")
    ):
        entry = json.loads(entry_evidence.read_bytes())
        orchestration = orchestrator(
            resolved["O"]["receipt"],
            resolved["U"]["receipt"],
            target_session,
            now,
            next_session,
            Path(resolved["O"]["path"]),
            Path(resolved["U"]["path"]),
            entry,
            True,
        )
        write_once(partial / "orchestrator.json", orchestration)
        if orchestration.get("state") in REPLAYABLE_STATES:
            replayed = replayer(
                raw_before,
                expected_blob,
                expected_hash,
                orchestration.get("commands") or [],
            )
            candidate = replayed.pop("candidate")
            write_once(partial / "candidate-journal.json", candidate)
            write_once(partial / "replay.json", replayed)
            state = "READY_ISOLATED_BUNDLE"
        else:
            state = "BLOCKED_ORCHESTRATOR"

    raw_after = journal.read_bytes()
    if raw_after != raw_before:
        raise ValueError("SOURCE_CHANGED_DURING_BUNDLE")

    receipt = {
        "schema_version": 1,
        "version": VERSION,
        "run_id": run_id,
        "state": state,
        "target_session": target_session,
        "input_classification": spec["input_classification"],
        "code_sha": spec["code_sha"],
        "bundle_script_sha256": spec["bundle_script_sha256"],
        "spec_sha256": spec_hash,
        "tracks": tracks,
        "orchestrator_state": orchestration.get("state") if orchestration else None,
        "replay_state": replayed.get("state") if replayed else None,
        "journal_source_before_sha256": digest_bytes(raw_before),
        "journal_source_after_sha256": digest_bytes(raw_after),
        "journal_source_unchanged": raw_after == raw_before,
        "formal_writes": 0,
        "production_pointer_switched": False,
        "real_orders": 0,
        "natural_cycle_credit": 0,
        "independent_factory_acceptance_required": True,
        "delivery_noop": False,
    }
    write_once(partial / "bundle-receipt.json", receipt)

    files = {}
    for path in sorted(partial.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        raw = path.read_bytes()
        files[path.name] = {"sha256": digest_bytes(raw), "bytes": len(raw)}
    manifest = {
        "schema_version": 1,
        "version": VERSION,
        "spec_sha256": spec_hash,
        "files": files,
    }
    write_once(partial / "manifest.json", manifest)

    if out_dir.exists():
        existing = verify_complete(out_dir, spec_hash)
        shutil.rmtree(partial)
        result = dict(existing)
        result["delivery_noop"] = True
        return result
    os.replace(partial, out_dir)
    verified = verify_complete(out_dir, spec_hash)
    if journal.read_bytes() != raw_before:
        raise ValueError("SOURCE_CHANGED_AFTER_PUBLICATION")
    return verified


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--target-session", required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--next-session", required=True)
    ap.add_argument("--verification-clock", required=True)
    ap.add_argument("--entry-evidence", type=Path, required=True)
    ap.add_argument("--journal", type=Path, required=True)
    ap.add_argument("--expected-blob", required=True)
    ap.add_argument("--expected-hash", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--code-sha", required=True)
    ap.add_argument(
        "--input-classification",
        choices=sorted(CLASSIFICATIONS),
        required=True,
    )
    args = ap.parse_args()
    result = build_bundle(
        root=args.root,
        target_session=args.target_session,
        now=args.now,
        next_session=args.next_session,
        verification_clock=args.verification_clock,
        entry_evidence=args.entry_evidence,
        journal=args.journal,
        expected_blob=args.expected_blob,
        expected_hash=args.expected_hash,
        out_dir=args.out_dir,
        run_id=args.run_id,
        code_sha=args.code_sha,
        input_classification=args.input_classification,
    )
    print(
        json.dumps(
            {
                "state": result["state"],
                "run_id": result["run_id"],
                "natural_cycle_credit": result["natural_cycle_credit"],
                "formal_writes": result["formal_writes"],
                "delivery_noop": result.get("delivery_noop", False),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["state"] == "READY_ISOLATED_BUNDLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())