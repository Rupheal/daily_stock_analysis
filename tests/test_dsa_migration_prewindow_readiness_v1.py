import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migration_prewindow",
    ROOT / "scripts/dsa_migration_prewindow_readiness_v1.py",
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_current_repository_is_prewindow_ready_only():
    r = mod.verify(ROOT)
    assert r["state"] == "PREWINDOW_READY_WAIT_NATURAL_PARALLEL"
    assert r["failed_checks"] == []
    assert r["owner_gate_reached"] is False
    assert r["runtime_pointer_switch_performed"] is False
    assert r["main_merge_performed"] is False
    assert r["paid_full_pool_scan_performed"] is False
    assert r["real_orders"] == 0
    assert r["future_observation_blockers"] == [
        "FUTURE_NATURAL_PARALLEL_20260922_REQUIRED",
        "SAME_TRIGGER_GATE_D_RECEIPT_REQUIRED",
        "POSTWINDOW_COMPARISON_REQUIRED",
        "INDEPENDENT_CENTRAL_AUDIT_REQUIRED",
    ]


def test_future_receipt_slots_are_blank():
    c = mod.load_json(ROOT, "docs/runtime/DSA_NATURAL_PARALLEL_20260922_CONTRACT.json")
    assert c["status"] == "ARMED_CONTRACT_ONLY_NOT_EVIDENCE"
    assert all(v is None for v in c["future_evidence_slots"].values())
