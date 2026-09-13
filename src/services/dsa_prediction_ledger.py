"""Append-only, content-addressed prediction provenance for DSA DEV research.

This module freezes prediction-time metadata separately from later outcomes.
It does not score a model, create a prediction, or authorize trading.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = (
    "run_id", "generated_at", "as_of", "universe_sha256", "input_sha256",
    "model_version", "config_sha256", "prediction_payload_sha256",
    "ranking_sha256", "status",
)


def canonical_hash(value) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _aware_timestamp(value: str, field: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt


def validate_prediction_record(record: dict) -> dict:
    if not isinstance(record, dict):
        raise TypeError("prediction record must be an object")
    missing = [key for key in _REQUIRED if record.get(key) in (None, "")]
    if missing:
        raise ValueError("missing prediction provenance: " + ",".join(missing))
    generated = _aware_timestamp(record["generated_at"], "generated_at")
    as_of = _aware_timestamp(record["as_of"], "as_of")
    if as_of > generated:
        raise ValueError("as_of cannot be later than generated_at")
    if generated > datetime.now(timezone.utc):
        raise ValueError("generated_at cannot be in the future")
    for field in (
        "universe_sha256", "input_sha256", "config_sha256",
        "prediction_payload_sha256", "ranking_sha256",
    ):
        if not _HEX64.fullmatch(str(record[field])):
            raise ValueError(f"{field} must be a lowercase sha256 digest")
    if not str(record["run_id"]).startswith("TRI-"):
        raise ValueError("run_id must be a TRIDENT run id")
    return dict(record)


def freeze_prediction(directory, record: dict) -> Path:
    """Write a content-addressed prediction once; an existing path is never overwritten."""
    record = validate_prediction_record(record)
    digest = canonical_hash(record)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{digest}.prediction.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def load_frozen_prediction(path) -> tuple[dict, str]:
    path = Path(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    validate_prediction_record(record)
    digest = canonical_hash(record)
    expected_name = f"{digest}.prediction.json"
    if path.name != expected_name:
        raise ValueError("frozen prediction was modified or renamed inconsistently")
    return record, digest


def append_outcome(prediction_path, outcome: dict) -> Path:
    """Append a Reality-Gap/outcome record without mutating the original prediction."""
    prediction, digest = load_frozen_prediction(prediction_path)
    if not isinstance(outcome, dict):
        raise TypeError("outcome must be an object")
    required = ("observed_at", "outcome_id", "status")
    missing = [key for key in required if outcome.get(key) in (None, "")]
    if missing:
        raise ValueError("missing outcome provenance: " + ",".join(missing))
    observed = _aware_timestamp(outcome["observed_at"], "observed_at")
    generated = _aware_timestamp(prediction["generated_at"], "generated_at")
    if observed < generated:
        raise ValueError("outcome cannot predate prediction")
    if observed > datetime.now(timezone.utc):
        raise ValueError("outcome observation cannot be in the future")
    linked = dict(outcome)
    supplied = linked.get("prediction_sha256")
    if supplied not in (None, digest):
        raise ValueError("outcome references the wrong prediction")
    linked["prediction_sha256"] = digest
    outcome_digest = canonical_hash(linked)
    target = Path(prediction_path).with_name(
        f"{digest}.outcome.{linked['outcome_id']}.{outcome_digest}.json"
    )
    with target.open("x", encoding="utf-8") as handle:
        json.dump(linked, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return target
