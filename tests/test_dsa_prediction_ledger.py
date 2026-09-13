import hashlib
import json
from datetime import datetime, timezone

import pytest

from src.services.dsa_prediction_ledger import (
    append_outcome, canonical_hash, freeze_prediction, load_frozen_prediction,
)


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def record():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": "TRI-DSA-DEV-20260913-004",
        "generated_at": now,
        "as_of": now,
        "universe_sha256": h("universe"),
        "input_sha256": h("input"),
        "model_version": "fixture-model-v1",
        "config_sha256": h("config"),
        "prediction_payload_sha256": h("prediction-payload"),
        "ranking_sha256": h("ranking"),
        "status": "SHADOW_RESEARCH_ONLY",
    }


def test_freeze_is_content_addressed_and_exclusive(tmp_path):
    r = record()
    p = freeze_prediction(tmp_path, r)
    assert p.name == canonical_hash(r) + ".prediction.json"
    loaded, digest = load_frozen_prediction(p)
    assert loaded == r
    assert digest == canonical_hash(r)
    with pytest.raises(FileExistsError):
        freeze_prediction(tmp_path, r)


def test_tampering_is_rejected(tmp_path):
    p = freeze_prediction(tmp_path, record())
    mutated = json.loads(p.read_text())
    mutated["status"] = "RETROACTIVE_PASS"
    p.write_text(json.dumps(mutated))
    with pytest.raises(ValueError, match="modified"):
        load_frozen_prediction(p)


def test_missing_provenance_is_rejected(tmp_path):
    r = record(); r.pop("universe_sha256")
    with pytest.raises(ValueError, match="missing prediction provenance"):
        freeze_prediction(tmp_path, r)


def test_outcome_is_append_only_and_links_original_hash(tmp_path):
    p = freeze_prediction(tmp_path, record())
    before = p.read_bytes()
    out = append_outcome(p, {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "outcome_id": "h1",
        "status": "MATURED",
        "reference_return_pct": "1.25",
    })
    assert p.read_bytes() == before
    payload = json.loads(out.read_text())
    assert payload["prediction_sha256"] == p.name.split(".")[0]
    assert payload["outcome_id"] == "h1"
    with pytest.raises(FileExistsError):
        append_outcome(p, {
            "observed_at": payload["observed_at"],
            "outcome_id": "h1",
            "status": "MATURED",
            "reference_return_pct": "1.25",
        })


def test_outcome_cannot_repoint_or_predate_prediction(tmp_path):
    r = record(); p = freeze_prediction(tmp_path, r)
    with pytest.raises(ValueError, match="wrong prediction"):
        append_outcome(p, {
            "observed_at": r["generated_at"], "outcome_id": "h1", "status": "MATURED",
            "prediction_sha256": "0" * 64,
        })
    with pytest.raises(ValueError, match="predate"):
        append_outcome(p, {
            "observed_at": "2020-01-01T00:00:00+00:00", "outcome_id": "h1", "status": "MATURED",
        })
