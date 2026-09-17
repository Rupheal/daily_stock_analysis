import importlib.util
from pathlib import Path
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_run058_o_rollout_controller.py"
spec = importlib.util.spec_from_file_location("run058", MODULE_PATH)
run058 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run058)


def scope():
    return {
        "target_session": "2026-09-17",
        "frozen_counts": {
            "O_universe": 660,
            "deterministic_ready": 608,
            "retained_isolated": 52,
            "no_repeat_ready": 3,
            "never_called": 605,
            "micro_batch_count": 303,
            "planning_tranche_count": 31,
        },
        "child_contract": {
            "proposed_child_run_id": "TRI-DSA-O-NATIVE-20260917-058A",
            "per_member_hard_cap_cny": "0.10",
            "child_hard_cap_cny": "0.20",
            "native_model_configuration": "O_DEEPSEEK_FLASH_NONTHINKING_v1",
            "required_pre_send_gates": ["free"],
            "required_post_send_gates": ["private"],
        },
        "resource_plan": {
            "model_http_requests": 0,
            "paid_data_calls": 0,
            "DeepSeek_API_cost_cny": 0,
            "automatic_recharge": False,
            "new_subscriptions": False,
            "real_orders": 0,
            "schedule_changes": 0,
        },
    }


def plan():
    batches = [
        {"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "hard_cap_cny": "0.20"},
        {"micro_batch_id": "O57-MB-002", "codes": ["00003", "00004"], "hard_cap_cny": "0.20"},
    ]
    # Fill the remainder with synthetic unique two-member batches only for count validation.
    next_code = 10000
    while len(batches) < 302:
        batches.append({
            "micro_batch_id": f"O57-MB-{len(batches)+1:03d}",
            "codes": [f"{next_code:05d}", f"{next_code+1:05d}"],
            "hard_cap_cny": "0.20",
        })
        next_code += 2
    batches.append({"micro_batch_id": "O57-MB-303", "codes": ["09999"], "hard_cap_cny": "0.10"})
    never = [c for b in batches for c in b["codes"]]
    # Synthetic tests need the frozen count of 605, but selection only concerns first batches.
    if len(never) != 605:
        # Replace filler arithmetic with a deterministic exact-length vector.
        need = 605 - 4
        rest = [f"{20000+i:05d}"[-5:] for i in range(need)]
        never = ["00001", "00002", "00003", "00004", *rest]
        batches = []
        for i in range(0, len(never), 2):
            codes = never[i:i+2]
            batches.append({
                "micro_batch_id": f"O57-MB-{len(batches)+1:03d}",
                "codes": codes,
                "hard_cap_cny": f"{0.10*len(codes):.2f}",
            })
    tranches = []
    for i in range(0, len(batches), 10):
        group = batches[i:i+10]
        tranches.append({
            "tranche_id": f"O57-TR-{len(tranches)+1:02d}",
            "micro_batch_ids": [b["micro_batch_id"] for b in group],
        })
    p = {
        "state": "PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN",
        "denominator": {"O_universe": 660, "deterministic_ready": 608, "retained_isolated": 52},
        "isolation": {"codes": ["90000"] * 52},
        "no_repeat": {"count_within_ready": 3, "spent_codes_within_ready": ["00700", "01024", "01810"]},
        "rollout": {
            "never_called_count": 605,
            "never_called_codes": never,
            "micro_batch_width": 2,
            "micro_batch_count": 303,
            "tranche_count": 31,
            "micro_batches": batches,
            "tranches": tranches,
            "send_authorized_by_run057": False,
        },
    }
    return p


def test_empty_ledger_selects_first_batch():
    r = run058.build(plan(), scope(), [], "planhash", None)
    assert r["state"] == "READY_CHILD_ENVELOPE"
    assert r["selected_child"]["micro_batch_id"] == "O57-MB-001"
    assert r["selected_child"]["codes"] == ["00001", "00002"]
    assert r["selected_child"]["provider_send_authorized_by_run058"] is False


def test_terminal_first_batch_moves_to_second():
    ledger = [{"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "ACCEPTED_NATIVE"}]
    r = run058.build(plan(), scope(), ledger, "planhash", "ledgerhash")
    assert r["selected_child"]["micro_batch_id"] == "O57-MB-002"


def test_raw_gate_block_is_terminal_without_retry():
    ledger = [{"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "RAW_GATE_BLOCK"}]
    r = run058.build(plan(), scope(), ledger, "planhash", "ledgerhash")
    assert r["selected_child"]["micro_batch_id"] == "O57-MB-002"


def test_claimed_reconcile_stops_controller():
    ledger = [{"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "CLAIMED_RECONCILE"}]
    r = run058.build(plan(), scope(), ledger, "planhash", "ledgerhash")
    assert r["state"] == "HOLD_NO_CHILD"
    assert r["selected_child"] is None


def test_private_failure_stops_controller():
    ledger = [{"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "PRIVATE_FINAL_FAIL"}]
    r = run058.build(plan(), scope(), ledger, "planhash", "ledgerhash")
    assert r["state"] == "HOLD_NO_CHILD"


def test_conflicting_ledger_state_rejected():
    ledger = [
        {"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "ACCEPTED_NATIVE"},
        {"micro_batch_id": "O57-MB-001", "codes": ["00001", "00002"], "status": "RAW_GATE_BLOCK"},
    ]
    with pytest.raises(ValueError, match="LEDGER_CONFLICTING_STATE"):
        run058.build(plan(), scope(), ledger, "planhash", "ledgerhash")


def test_forbidden_code_never_selected():
    p = plan()
    p["rollout"]["micro_batches"][0]["codes"] = ["00700", "00002"]
    with pytest.raises(ValueError, match="BATCH_NOT_NEVER_CALLED|BATCH_CONTAINS_FORBIDDEN_CODE"):
        run058.build(p, scope(), [], "planhash", None)
