from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.dsa_shadow_cycle_acceptance_v1 import validate

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def base_bundle(tmp_path: Path) -> dict:
    evidence = {}
    for name in (
        "O_decision","U_decision","adapter_result","gate_d_receipt",
        "dashboard","runtime_binding","central_audit",
    ):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps({"name": name}), encoding="utf-8")
        evidence[name] = {"path": p.name, "sha256": sha(p)}
    return {
        "schema_version": 1,
        "cycle_id": "DSA-SHADOW-20260928-001",
        "mode": "REAL_SHADOW",
        "target_session": "2026-09-28",
        "trigger_id": "TRIGGER-20260928-001",
        "synthetic": False,
        "replay": False,
        "dry_run": False,
        "observed_at": "2026-09-28T09:40:00+08:00",
        "evidence": evidence,
        "tracks": {
            "O": {
                "target_session": "2026-09-28",
                "trigger_id": "TRIGGER-20260928-001",
                "actual_input": True,
                "frozen_version": "O@abc",
                "state": "WAIT",
            },
            "U": {
                "target_session": "2026-09-28",
                "trigger_id": "TRIGGER-20260928-001",
                "actual_input": True,
                "frozen_version": "U@def",
                "state": "NO_ENTRY_POLICY_BLOCK",
            },
        },
        "journal": {
            "parent_hash": "a" * 64,
            "result_hash": "b" * 64,
            "append_count": 2,
            "cas_verified": True,
            "idempotent_replay_verified": True,
            "single_writer_verified": True,
        },
        "delivery": {
            "immutable_outputs": True,
            "dashboard_updated": True,
            "machine_receipt_written": True,
        },
        "scheduler": {
            "eligible_session_schedule_observed": True,
            "recovery_verified": True,
        },
        "audit": {
            "accepted": True,
            "trigger_id": "TRIGGER-20260928-001",
            "target_session": "2026-09-28",
        },
        "side_effects": {
            "candidate_authority_writes": 0,
            "real_orders": 0,
            "production_pointer_switched": False,
        },
        "resources": {
            "paid_requests": 0,
            "auto_recharge": False,
        },
    }

def test_eligible_real_session_still_requires_factory_acceptance(tmp_path: Path):
    out = validate(base_bundle(tmp_path), tmp_path)
    assert out["state"] == "ELIGIBLE_FOR_INDEPENDENT_FACTORY_ACCEPTANCE"
    assert out["natural_cycle_credit"] == 0
    assert out["independent_factory_acceptance_required"] is True

def test_weekend_cannot_count(tmp_path: Path):
    b = base_bundle(tmp_path)
    b["target_session"] = "2026-09-26"
    for row in b["tracks"].values():
        row["target_session"] = "2026-09-26"
    b["audit"]["target_session"] = "2026-09-26"
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert "TARGET_NOT_XHKG_SESSION" in out["blockers"]

def test_synthetic_replay_and_dry_run_never_count(tmp_path: Path):
    b = base_bundle(tmp_path)
    b["synthetic"] = True
    b["replay"] = True
    b["dry_run"] = True
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert {"SYNTHETIC_NOT_ALLOWED","REPLAY_NOT_ALLOWED","DRY_RUN_NOT_ALLOWED"} <= set(out["blockers"])

def test_hash_drift_fails_closed(tmp_path: Path):
    b = base_bundle(tmp_path)
    p = tmp_path / "O_decision.json"
    p.write_text('{"tampered":true}', encoding="utf-8")
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert "EVIDENCE_HASH_MISMATCH:O_decision" in out["blockers"]

def test_trigger_and_session_must_match_across_tracks_and_audit(tmp_path: Path):
    b = base_bundle(tmp_path)
    b["tracks"]["U"]["trigger_id"] = "OTHER"
    b["audit"]["target_session"] = "2026-09-29"
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert "U_TRIGGER_MISMATCH" in out["blockers"]
    assert "AUDIT_SESSION_MISMATCH" in out["blockers"]

def test_journal_and_scheduler_guards_are_conjunctive(tmp_path: Path):
    b = base_bundle(tmp_path)
    b["journal"]["cas_verified"] = False
    b["scheduler"]["recovery_verified"] = False
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert "JOURNAL_CAS_VERIFIED_REQUIRED" in out["blockers"]
    assert "RECOVERY_EVIDENCE_REQUIRED" in out["blockers"]

def test_real_orders_or_pointer_switch_are_fatal(tmp_path: Path):
    b = base_bundle(tmp_path)
    b["side_effects"]["real_orders"] = 1
    b["side_effects"]["production_pointer_switched"] = True
    out = validate(b, tmp_path)
    assert out["state"] == "BLOCKED"
    assert "REAL_ORDERS_NONZERO" in out["blockers"]
    assert "PRODUCTION_POINTER_SWITCHED" in out["blockers"]
