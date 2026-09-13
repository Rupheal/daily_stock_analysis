"""Fail-closed point-in-time manifest validation for historical DSA predictions.

A passing manifest means only that the supplied evidence is timestamped and admissible
at the decision clock. It does not create a prediction or prove historical truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _ts(value, name):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return dt


def _sha(value, name):
    if not _HEX64.fullmatch(str(value or "")):
        raise ValueError(f"{name} must be sha256")
    return str(value)


def validate_pit_manifest(manifest: dict) -> dict:
    """Return a canonical acceptance receipt or reject non-PIT inputs."""
    if not isinstance(manifest, dict):
        raise TypeError("manifest must be an object")
    required = ("decision_at", "universe", "evidence", "model_version", "config_sha256")
    missing = [k for k in required if manifest.get(k) in (None, "")]
    if missing:
        raise ValueError("missing PIT manifest fields: " + ",".join(missing))
    decision = _ts(manifest["decision_at"], "decision_at")
    _sha(manifest["config_sha256"], "config_sha256")

    universe = manifest["universe"]
    for key in ("universe_id", "effective_at", "available_at", "content_sha256", "source"):
        if universe.get(key) in (None, ""):
            raise ValueError("universe missing PIT provenance: " + key)
    effective = _ts(universe["effective_at"], "universe.effective_at")
    available = _ts(universe["available_at"], "universe.available_at")
    _sha(universe["content_sha256"], "universe.content_sha256")
    if effective > decision or available > decision:
        raise ValueError("universe was not available/effective at decision time")

    evidence = manifest["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("evidence must be a non-empty list")
    ids = set()
    accepted = []
    for row in evidence:
        for key in ("evidence_id", "available_at", "content_sha256", "source", "vintage_status"):
            if row.get(key) in (None, ""):
                raise ValueError(f"evidence missing PIT provenance: {key}")
        if row["evidence_id"] in ids:
            raise ValueError("duplicate evidence_id")
        ids.add(row["evidence_id"])
        row_available = _ts(row["available_at"], "evidence.available_at")
        _sha(row["content_sha256"], "evidence.content_sha256")
        if row_available > decision:
            raise ValueError("future evidence leaked into historical decision")
        if row["vintage_status"] != "verified_as_available_then":
            raise ValueError("historical vintage is not verified")
        accepted.append(row["evidence_id"])

    receipt = {
        "decision_at": manifest["decision_at"],
        "universe_id": universe["universe_id"],
        "model_version": manifest["model_version"],
        "config_sha256": manifest["config_sha256"],
        "evidence_ids": accepted,
        "pit_input_admissible": True,
        "prediction_generated": False,
    }
    receipt["manifest_sha256"] = canonical_hash(manifest)
    return receipt
