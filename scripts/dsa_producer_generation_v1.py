"""Record a just-produced file, without claiming consumer availability/acceptance."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def record_generated(receipt: Path, account: str, target_session: str) -> Path:
    if account not in ("O", "U"):
        raise ValueError("PRODUCER_ACCOUNT_INVALID")
    raw = receipt.read_bytes()
    data = json.loads(raw)
    if data.get("target_session") != target_session:
        raise ValueError("PRODUCER_SESSION_MISMATCH")
    out = receipt.with_name(receipt.name + ".generation.json")
    digest = hashlib.sha256(raw).hexdigest()
    # A retry preserves the first observation, rather than inventing a new one.
    if out.exists():
        old = json.loads(out.read_bytes())
        if (old.get("receipt_sha256"), old.get("account"), old.get("target_session")) != (
                digest, account, target_session):
            raise ValueError("PRODUCER_GENERATION_CONFLICT")
        return out
    observation = {"schema_version": 1, "account": account,
                   "target_session": target_session, "receipt_sha256": digest,
                   "generation_observed_at": datetime.now(timezone.utc).isoformat(),
                   "event": "LOCAL_RECEIPT_BYTES_OBSERVED_AFTER_GENERATION",
                   "consumer_available_at": None, "formal_accepted_at": None,
                   "signal_timing_complete": False}
    with out.open("x", encoding="utf-8") as stream:
        json.dump(observation, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return out
