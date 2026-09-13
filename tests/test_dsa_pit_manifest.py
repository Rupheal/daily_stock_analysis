import hashlib
from copy import deepcopy

import pytest

from src.services.dsa_pit_manifest import validate_pit_manifest


def h(text): return hashlib.sha256(text.encode()).hexdigest()


def good():
    return {
        "decision_at": "2025-06-03T09:25:00+08:00",
        "universe": {
            "universe_id": "fixture-PIT-U",
            "effective_at": "2025-06-03T00:00:00+08:00",
            "available_at": "2025-06-03T08:00:00+08:00",
            "content_sha256": h("universe"),
            "source": "fixture exchange archive"
        },
        "evidence": [{
            "evidence_id": "price:HK01810:2025-06-02",
            "available_at": "2025-06-02T16:30:00+08:00",
            "content_sha256": h("evidence"),
            "source": "fixture dated archive",
            "vintage_status": "verified_as_available_then"
        }],
        "model_version": "fixture-model-v1",
        "config_sha256": h("config")
    }


def test_valid_manifest_is_admissible_but_not_a_prediction():
    result = validate_pit_manifest(good())
    assert result["pit_input_admissible"] is True
    assert result["prediction_generated"] is False


def test_future_evidence_is_rejected():
    m = good(); m["evidence"][0]["available_at"] = "2025-06-03T10:00:00+08:00"
    with pytest.raises(ValueError, match="future evidence"):
        validate_pit_manifest(m)


def test_unverified_vintage_is_rejected():
    m = good(); m["evidence"][0]["vintage_status"] = "retrieved_later_unknown_vintage"
    with pytest.raises(ValueError, match="vintage"):
        validate_pit_manifest(m)


def test_late_universe_membership_is_rejected():
    m = good(); m["universe"]["effective_at"] = "2025-06-04T00:00:00+08:00"
    with pytest.raises(ValueError, match="universe was not"):
        validate_pit_manifest(m)


def test_missing_availability_and_duplicate_ids_fail_closed():
    m = good(); del m["evidence"][0]["available_at"]
    with pytest.raises(ValueError, match="missing PIT provenance"):
        validate_pit_manifest(m)
    m = good(); m["evidence"].append(deepcopy(m["evidence"][0]))
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        validate_pit_manifest(m)
