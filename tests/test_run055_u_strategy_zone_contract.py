import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_run055_u_strategy_zone_contract.py"
spec = importlib.util.spec_from_file_location("run055", MODULE_PATH)
run055 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run055)


def make_risk_rows(ineligible_code="09618"):
    rows = []
    for i in range(45):
        code = f"{i+1:05d}"
        rows.append({
            "code": code,
            "name": f"N{code}",
            "eligible": True,
            "sector_risk_evidence": {"state": "NOT_SEPARATELY_SOURCE_BOUND"},
            "issuer_primary_review": {"full_risk_coverage_proven": False},
        })
    # Replace one code with the retained ineligible member while preserving 45 unique codes.
    rows[-1]["code"] = ineligible_code
    rows[-1]["name"] = "JD-SW"
    rows[-1]["eligible"] = False
    return rows


def test_build_contract_is_fail_closed_and_creates_no_buy():
    result = run055.build(
        facts={},
        handoff={},
        macro={"regime": {"position_ceiling_pct": 30}},
        risk={"rows": make_risk_rows()},
    )
    assert result["denominator"] == 45
    assert result["eligible"] == 44
    assert result["retained_ineligible"] == ["09618"]
    assert result["counts"]["approved_numeric_zones"] == 0
    assert result["counts"]["pending_formal_decision"] == 44
    assert result["counts"]["withheld_unknown"] == 1
    assert result["counts"]["risk_missingness_explicit"] == 45
    assert result["counts"]["qualified_buy_created"] == 0
    assert result["resource_accounting"]["model_http_requests"] == 0
    assert result["resource_accounting"]["real_orders"] == 0
    for row in result["rows"]:
        assert row["lower"] is None and row["upper"] is None
        assert row["buy_permission_from_run055"] is False
        assert row["execution_quote_used_to_construct_zone"] is False


def test_wrong_macro_cap_is_rejected():
    with pytest.raises(ValueError, match="RUN053_MACRO_CAP_MISMATCH"):
        run055.build({}, {}, {"regime": {"position_ceiling_pct": 40}}, {"rows": make_risk_rows()})


def test_wrong_ineligible_identity_is_rejected():
    with pytest.raises(ValueError, match="EXPECTED_09618_ONLY_INELIGIBLE"):
        run055.build({}, {}, {"regime": {"position_ceiling_pct": 30}}, {"rows": make_risk_rows("09999")})


def test_numeric_zone_requires_formal_decision_rationale_and_source():
    row = {
        "zone_status": "APPROVED_NUMERIC",
        "execution_quote_used_to_construct_zone": False,
        "later_price_move_can_widen_zone": False,
        "lower": 10,
        "upper": 11,
        "formal_strategy_decision_id": None,
        "rationale": None,
        "source_evidence": [],
    }
    with pytest.raises(ValueError, match="NUMERIC_ZONE_NEEDS_FORMAL_DECISION_AND_RATIONALE"):
        run055.validate_zone_row(row)


def test_execution_quote_cannot_construct_strategy_zone():
    row = {
        "zone_status": "WITHHELD_UNKNOWN",
        "execution_quote_used_to_construct_zone": True,
        "later_price_move_can_widen_zone": False,
        "lower": None,
        "upper": None,
    }
    with pytest.raises(ValueError, match="EXECUTION_QUOTE_MUST_NOT_CONSTRUCT_STRATEGY_ZONE"):
        run055.validate_zone_row(row)


def test_pending_or_withheld_zone_must_not_have_numeric_bounds():
    row = {
        "zone_status": "PENDING_FORMAL_DECISION",
        "execution_quote_used_to_construct_zone": False,
        "later_price_move_can_widen_zone": False,
        "lower": 10,
        "upper": 11,
    }
    with pytest.raises(ValueError, match="WITHHELD_OR_PENDING_ZONE_MUST_NOT_HAVE_NUMERIC_BOUNDS"):
        run055.validate_zone_row(row)
