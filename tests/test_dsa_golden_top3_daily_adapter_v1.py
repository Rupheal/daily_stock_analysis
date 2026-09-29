import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dsa_golden_top3_daily_adapter_v1 as ga

TARGET = "2026-09-30"


def write_json(path: Path, obj: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return path


def o_receipt(*, qualified_buy: int = 0, duplicate: bool = False) -> dict:
    rows = [
        {
            "code": "00148",
            "name": "KINGBOARD HOLDINGS",
            "rank": 1,
            "sentiment_score": 59,
            "action": "buy" if qualified_buy else "hold",
            "action_family": "buy" if qualified_buy else "hold",
            "buyable_verified": bool(qualified_buy),
        },
        {
            "code": "00148" if duplicate else "00177",
            "name": "JIANGSU EXPRESSWAY",
            "rank": 2,
            "sentiment_score": 58,
            "action": "hold",
            "action_family": "hold",
        },
        {
            "code": "00552",
            "name": "CHINA COMMUNICATIONS SERVICES",
            "rank": 3,
            "sentiment_score": 57,
            "action": "hold",
            "action_family": "hold",
        },
    ]
    return {
        "status": "ACCEPTED_O_FORMAL_TOP3",
        "target_session": TARGET,
        "official_O_denominator": 660,
        "operational_O_denominator": 657,
        "missing_count": 0,
        "qualified_buy_in_Top3": qualified_buy,
        "Top3": rows,
    }


def u_receipt() -> dict:
    return {
        "state": "PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
        "target_session": TARGET,
        "denominator": 45,
        "formal_valid_rows": 0,
        "qualified_BUY": 0,
        "Top3": [],
        "Top10": [
            {"code": "00700", "name": "TENCENT", "rank": 1, "score": 90, "formal_action": "BUY"},
            {"code": "09988", "name": "BABA-W", "rank": 2, "score": 89, "formal_action": "BUY"},
            {"code": "03690", "name": "MEITUAN-W", "rank": 3, "score": 88, "formal_action": "BUY"},
        ],
        "rows": [],
    }


def setup_formal_receipts(tmp_path: Path, *, qualified_buy: int = 0, duplicate: bool = False) -> tuple[Path, Path]:
    runtime = tmp_path / "docs" / "runtime"
    o_path = write_json(runtime / "O_PRODUCTION_FORMAL_LATEST.json", o_receipt(qualified_buy=qualified_buy, duplicate=duplicate))
    u_path = write_json(runtime / "U_PRODUCTION_FORMAL_LATEST.json", u_receipt())
    return o_path, u_path


def test_golden_projection_keeps_o_and_u_independent_and_does_not_promote_top10(tmp_path):
    setup_formal_receipts(tmp_path)

    result = ga.build_golden_daily(tmp_path, TARGET)

    assert result["state"] == "READY"
    assert result["decision_state"] == "WAIT_NO_BUY"
    assert [row["code"] for row in result["tracks"]["O"]["top3"]] == ["00148", "00177", "00552"]
    assert result["tracks"]["U"]["top3"] == []
    assert result["tracks"]["O"]["state"] == "WAIT"
    assert result["tracks"]["U"]["state"] == "WAIT"
    assert result["qualified_buy_total"] == 0
    assert result["authority"] == "NONE_PROJECTION_ONLY"
    assert result["side_effects"] == {
        "model_calls": 0,
        "authority_writes": 0,
        "simulation_writes": 0,
        "broker_orders": 0,
        "real_orders": 0,
    }


def test_existing_qualified_buy_is_projected_but_adapter_does_not_create_execution_authority(tmp_path):
    setup_formal_receipts(tmp_path, qualified_buy=1)

    result = ga.build_golden_daily(tmp_path, TARGET)

    assert result["decision_state"] == "QUALIFIED_BUY_PRESENT"
    assert result["tracks"]["O"]["qualified_buy"] == 1
    assert result["tracks"]["O"]["top3"][0]["action"] == "BUY"
    assert result["tracks"]["O"]["top3"][0]["buyable_verified"] is True
    assert result["authority"] == "NONE_PROJECTION_ONLY"
    assert "commands" not in result
    assert "entry" not in result


def test_missing_current_formal_receipt_fails_closed(tmp_path):
    runtime = tmp_path / "docs" / "runtime"
    write_json(runtime / "O_PRODUCTION_FORMAL_LATEST.json", o_receipt())

    with pytest.raises(ga.GoldenAdapterError, match="FORMAL_RECEIPTS_NOT_READY"):
        ga.build_golden_daily(tmp_path, TARGET)


def test_duplicate_top3_code_fails_closed(tmp_path):
    setup_formal_receipts(tmp_path, duplicate=True)

    with pytest.raises(ga.GoldenAdapterError, match="DUPLICATE_TOP3_CODE_O"):
        ga.build_golden_daily(tmp_path, TARGET)


def test_projection_is_deterministic_and_hash_binds_exact_source_bytes(tmp_path):
    o_path, u_path = setup_formal_receipts(tmp_path)

    first = ga.build_golden_daily(tmp_path, TARGET)
    second = ga.build_golden_daily(tmp_path, TARGET)

    assert first == second
    assert first["sources"]["O"]["sha256"] == hashlib.sha256(o_path.read_bytes()).hexdigest()
    assert first["sources"]["U"]["sha256"] == hashlib.sha256(u_path.read_bytes()).hexdigest()
    assert len(first["deterministic_receipt_sha256"]) == 64


def test_adapter_does_not_mutate_formal_receipts(tmp_path):
    o_path, u_path = setup_formal_receipts(tmp_path)
    before = {o_path: o_path.read_bytes(), u_path: u_path.read_bytes()}

    ga.build_golden_daily(tmp_path, TARGET)

    assert {path: path.read_bytes() for path in before} == before


def test_documented_package_import_works():
    import importlib

    sys.path.insert(0, str(ROOT))
    try:
        sys.modules.pop("scripts.dsa_golden_top3_daily_adapter_v1", None)
        module = importlib.import_module("scripts.dsa_golden_top3_daily_adapter_v1")
        assert callable(module.build_golden_daily)
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)


def test_source_change_after_resolution_fails_closed(tmp_path, monkeypatch):
    o_path, u_path = setup_formal_receipts(tmp_path)
    old_o = json.loads(o_path.read_text())
    old_u = json.loads(u_path.read_text())
    changed_o = dict(old_o)
    changed_o["Top3"] = [dict(row) for row in old_o["Top3"]]
    changed_o["Top3"][0]["sentiment_score"] = 1
    write_json(o_path, changed_o)

    monkeypatch.setattr(
        ga,
        "resolve",
        lambda root, target: {
            "state": "READY",
            "O": {"path": str(o_path), "receipt": old_o},
            "U": {"path": str(u_path), "receipt": old_u},
        },
    )

    with pytest.raises(ga.GoldenAdapterError, match="SOURCE_CHANGED_AFTER_RESOLUTION_O"):
        ga.build_golden_daily(tmp_path, TARGET)


def test_top3_rank_sequence_must_be_contiguous(tmp_path):
    o_path, _ = setup_formal_receipts(tmp_path)
    receipt = json.loads(o_path.read_text())
    receipt["Top3"][1]["rank"] = 3
    receipt["Top3"][2]["rank"] = 2
    write_json(o_path, receipt)

    with pytest.raises(ga.GoldenAdapterError, match="TOP3_RANK_SEQUENCE_INVALID_O"):
        ga.build_golden_daily(tmp_path, TARGET)
