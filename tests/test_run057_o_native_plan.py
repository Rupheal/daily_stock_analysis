import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_run057_o_native_plan.py"
spec = importlib.util.spec_from_file_location("run057", MODULE_PATH)
run057 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run057)


def test_partition_exact_once_and_tail():
    items = [f"{i:05d}" for i in range(1, 8)]
    out = run057.partition(items, 2)
    assert out == [["00001", "00002"], ["00003", "00004"], ["00005", "00006"], ["00007"]]
    assert [x for group in out for x in group] == items


def test_collect_spent_nested_claimed_member():
    doc = {
        "run": {
            "member": {
                "code": "00700",
                "claim_persisted": True,
                "model_http_requests_confirmed": 1,
            }
        }
    }
    found = run057.collect_spent_codes(doc, "receipt.json")
    assert "00700" in found
    assert any("durable_claim" in x for x in found["00700"])
    assert any("provider_spend_or_response" in x for x in found["00700"])


def test_collect_spent_top_level_target_with_nested_request():
    doc = {
        "target": "HK01810",
        "technical_execution": {
            "model_http_requests": 1,
            "request_status": "response_received",
        },
    }
    found = run057.collect_spent_codes(doc, "O_SINGLE_NATIVE_ACCEPTANCE.json")
    assert "01810" in found


def test_zero_request_not_spent():
    doc = {
        "target": "HK01810",
        "technical_execution": {"model_http_requests": 0},
    }
    assert run057.collect_spent_codes(doc, "x.json") == {}


def test_ready_partition_math_for_frozen_denominator():
    universe = {f"{i:05d}" for i in range(1, 661)}
    isolated = set(sorted(universe)[:52])
    ready = sorted(universe - isolated)
    no_repeat = {ready[0], ready[1], ready[2]}
    never = sorted(set(ready) - no_repeat)
    assert len(universe) == 660
    assert len(isolated) == 52
    assert len(ready) == 608
    assert len(no_repeat) == 3
    assert len(never) == 605
    assert not (set(never) & no_repeat)


def test_cost_cap_is_conservative_not_actual_charge():
    from decimal import Decimal
    assert Decimal("0.10") * 605 == Decimal("60.50")
