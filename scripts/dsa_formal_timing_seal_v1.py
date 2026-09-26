#!/usr/bin/env python3
"""Seal a NEW candidate formal receipt with externally verified timing evidence.

No clock defaults, providers, Authority writes or workflow activation. Evidence
authenticity/approval is an upstream obligation; this checks binding and syntax.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import tempfile
from datetime import date
from pathlib import Path

try:
    from scripts.dsa_production_orchestrator_v1 import (
        build_signal, classify_o, classify_u,
    )
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from dsa_production_orchestrator_v1 import (
        build_signal, classify_o, classify_u,
    )


def seal(raw: bytes, evidence: dict, now: str) -> bytes:
    source = json.loads(raw)
    if not isinstance(source, dict) or not isinstance(evidence, dict):
        raise ValueError("TIMING_OBJECT_REQUIRED")
    if "signal_timing" in source or "signal_timing_evidence" in source:
        raise ValueError("RECEIPT_ALREADY_SEALED")
    if evidence.get("receipt_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("TIMING_RECEIPT_HASH_MISMATCH")
    if evidence.get("target_session") != source.get("target_session"):
        raise ValueError("TIMING_SESSION_MISMATCH")
    account = evidence.get("account")
    if account not in ("O", "U"):
        raise ValueError("TIMING_ACCOUNT_INVALID")
    # A U attestation must never relabel an O producer output, or vice versa.
    if account == "O":
        if "official_O_denominator" not in source or "formal_valid_rows" in source:
            raise ValueError("TIMING_PRODUCER_MISMATCH")
    elif "formal_valid_rows" not in source or "official_O_denominator" in source:
        raise ValueError("TIMING_PRODUCER_MISMATCH")
    timing = evidence.get("signal_timing")
    refs = evidence.get("field_evidence")
    if not isinstance(timing, dict) or not isinstance(refs, dict):
        raise ValueError("TIMING_EVIDENCE_REQUIRED")
    for value in (source.get("target_session"), timing.get("next_session")):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("TIMING_SESSION_INVALID")
        date.fromisoformat(value)
    if timing["next_session"] < source["target_session"]:
        raise ValueError("TIMING_NEXT_SESSION_BEFORE_SOURCE")
    for field in ("cutoff", "available_at", "valid_until", "next_session"):
        ref = refs.get(field)
        if (not isinstance(ref, dict) or not isinstance(ref.get("source"), str)
                or not ref["source"].strip()
                or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", "")))):
            raise ValueError("TIMING_FIELD_EVIDENCE_MISSING:" + field)
    candidate = dict(source)
    candidate["signal_timing"] = timing
    candidate["signal_timing_evidence"] = evidence
    payload = (json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    classify = classify_o if account == "O" else classify_u
    track = classify(candidate, source["target_session"])
    # Exercise the actual consumer validator; never fork timing semantics.
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "candidate.json"
        path.write_bytes(payload)
        build_signal(track, path, now, timing.get("next_session"), receipt=candidate)
    return payload


def write_candidate(source: Path, evidence_path: Path, out: Path, now: str) -> dict:
    if out.resolve() in (source.resolve(), evidence_path.resolve()):
        raise ValueError("TIMING_OUTPUT_MUST_BE_SEPARATE")
    payload = seal(source.read_bytes(), json.loads(evidence_path.read_bytes()), now)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Never truncate an existing receipt. Identical retries are harmless.
    try:
        with out.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if out.read_bytes() != payload:
            raise ValueError("TIMING_OUTPUT_CONFLICT") from None
    return {"state": "TIMING_CANDIDATE_SEALED",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "authority_verified_by_this_tool": False,
            "production_activated": False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--timing-evidence", type=Path, required=True)
    ap.add_argument("--now", required=True, help="Explicit validation clock, never source availability")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    try:
        result = write_candidate(a.receipt, a.timing_evidence, a.out, a.now)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # No input payloads, credentials or private paths in diagnostic output.
        print(json.dumps({"state": "BLOCKED", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
