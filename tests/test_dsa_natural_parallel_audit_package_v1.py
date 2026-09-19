import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dsa_natural_parallel_audit_package_v1 import build_audit_package


def write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def fixture(tmp_path: Path, state="ELIGIBLE_FOR_CENTRAL_AUDIT"):
    att = write(tmp_path, "att.json", {
        "status": "PASS_SAME_CUTOFF_INPUTS",
        "target_session": "2026-09-18",
        "next_session": "2026-09-21",
        "cutoff_at": "2026-09-21T09:25:00+08:00",
        "sealed_at": "2026-09-21T09:22:00+08:00",
        "input_sha256": {"o_receipt": "a"*64, "u_receipt": "b"*64, "foundation_journal": "c"*64},
    })
    cmp = write(tmp_path, "cmp.json", {
        "classification": "NATURAL_PARALLEL_COMPARISON",
        "natural_parallel_attestation": {"status": "PASS"},
        "read_only_contract": {
            "authoritative_journal_write_count": 0,
            "candidate_journal_write_count": 0,
            "real_orders": 0,
        },
        "comparison": {
            "migration_acceptance": state,
            "trade_action_equivalent": state != "BLOCKED_ACTION_DIVERGENCE",
            "control_state_equivalent": state == "ELIGIBLE_FOR_CENTRAL_AUDIT",
            "all_equivalent": state == "ELIGIBLE_FOR_CENTRAL_AUDIT",
        },
    })
    active = write(tmp_path, "active.json", {
        "session": "2026-09-21",
        "shadow_simulation_only": True,
        "real_orders": 0,
        "timeline": [{
            "stage": "FREEZE_PRECHECK",
            "journal_raw_sha256": "c"*64,
        }],
    })
    prov = write(tmp_path, "prov.json", {
        "github_run_id": 123,
        "github_run_attempt": 1,
        "trigger_commit": "d"*40,
        "seal_artifact_uploaded_before_cutoff": True,
    })
    return att, cmp, active, prov


@pytest.mark.parametrize("state,next_step", [
    ("ELIGIBLE_FOR_CENTRAL_AUDIT", "INDEPENDENT_CENTRAL_AUDIT"),
    ("CENTRAL_AUDIT_REQUIRED_CONTROL_STATE_DIVERGENCE", "REVIEW_CONTROL_STATE_DIVERGENCE"),
    ("BLOCKED_ACTION_DIVERGENCE", "BLOCK_MIGRATION"),
])
def test_builds_expected_package(tmp_path, state, next_step):
    paths = fixture(tmp_path, state)
    r = build_audit_package(*paths)
    assert r["status"] == state
    assert r["central_audit_next"] == next_step
    assert r["safety"]["real_orders"] == 0
    assert r["safety"]["candidate_journal_writes"] == 0


def test_rejects_non_natural_comparison(tmp_path):
    att, cmp, active, prov = fixture(tmp_path)
    payload = json.loads(cmp.read_text())
    payload["classification"] = "ENGINEERING_REPLAY_NOT_NATURAL_PARALLEL"
    cmp.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="COMPARISON_NOT_NATURAL_PARALLEL"):
        build_audit_package(att, cmp, active, prov)


def test_rejects_real_orders(tmp_path):
    att, cmp, active, prov = fixture(tmp_path)
    payload = json.loads(active.read_text())
    payload["real_orders"] = 1
    active.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="ACTIVE_RECEIPT_REAL_ORDERS_NONZERO"):
        build_audit_package(att, cmp, active, prov)


def test_rejects_outcome_session_mismatch(tmp_path):
    att, cmp, active, prov = fixture(tmp_path)
    payload = json.loads(active.read_text())
    payload["session"] = "2026-09-22"
    active.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="OUTCOME_SESSION_MISMATCH"):
        build_audit_package(att, cmp, active, prov)


def test_rejects_active_freeze_journal_mismatch(tmp_path):
    att, cmp, active, prov = fixture(tmp_path)
    payload = json.loads(active.read_text())
    payload["timeline"][0]["journal_raw_sha256"] = "f" * 64
    active.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="SEALED_JOURNAL_NOT_EQUAL_ACTIVE_FREEZE"):
        build_audit_package(att, cmp, active, prov)


def test_rejects_missing_freeze_precheck(tmp_path):
    att, cmp, active, prov = fixture(tmp_path)
    payload = json.loads(active.read_text())
    payload["timeline"] = []
    active.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="ACTIVE_FREEZE_PRECHECK_NOT_UNIQUE"):
        build_audit_package(att, cmp, active, prov)
