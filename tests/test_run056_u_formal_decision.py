import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run056_u_formal_decision.py"
spec = importlib.util.spec_from_file_location("run056", MODULE_PATH)
run056 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run056)


REASONS = [
    "TREND_POSITIVE","TREND_NEGATIVE","RELATIVE_STRENGTH","RELATIVE_WEAKNESS",
    "MOMENTUM_IMPROVING","MOMENTUM_WEAK","VOLUME_CONFIRMING","VOLUME_WEAK",
    "SUPPORT_HOLD","SUPPORT_AT_RISK","CAPITAL_ACCUMULATION_VERIFIED",
    "CAPITAL_OUTFLOW_VERIFIED","CAPITAL_EVIDENCE_LIMITED","ISSUER_EVENT_SUPPORTIVE",
    "ISSUER_EVENT_RISK","COMPANY_RISK_COVERAGE_LIMITED","SECTOR_RISK_NOT_SOURCE_BOUND",
    "DATA_SEMANTIC_RISK","OVEREXTENDED","NO_EDGE"
]
SCOPE = {
    "formal_reason_code_set": REASONS,
    "zone_contract": {"allowed_anchor_names": [
        "PRIOR_SUPPORT20","PRIOR_MA20","PRIOR_MA10","PRIOR_MA5","PRIOR_CLOSE",
        "CURRENT_LOW","CURRENT_OPEN","CURRENT_CLOSE"
    ]},
    "zone_thesis_code_set": ["SUPPORT_RETEST","MA_RECLAIM","CLOSE_HOLD","BREAKOUT_RETEST","WITHHOLD"],
}


def source(code="00700", capital_state="VERIFIED"):
    return {
        "code": code,
        "name": "TEST",
        "eligible": True,
        "sector_risk_state": "NOT_SEPARATELY_SOURCE_BOUND",
        "capital": {"state":capital_state,"date":"2026-09-16","persistence":"ONE_SESSION_ONLY_NOT_A_TREND"},
        "allowed_zone_anchors": {
            "PRIOR_SUPPORT20": 90.0,
            "PRIOR_MA20": 95.0,
            "PRIOR_MA10": 98.0,
            "PRIOR_MA5": 99.0,
            "PRIOR_CLOSE": 100.0,
            "CURRENT_LOW": 97.0,
            "CURRENT_OPEN": 99.0,
            "CURRENT_CLOSE": 101.0,
        },
        "risk_missingness_explicit": True,
    }


def buy_row(code="00700", score=82):
    return {
        "code":code,"decision":"BUY_CANDIDATE","score":score,"confidence":"MEDIUM",
        "reason_codes":["TREND_POSITIVE","SUPPORT_HOLD","SECTOR_RISK_NOT_SOURCE_BOUND"],
        "zone_low_anchor":"PRIOR_MA10","zone_high_anchor":"CURRENT_CLOSE","zone_thesis_code":"MA_RECLAIM"
    }


def watch_row(code="00700", score=60):
    return {
        "code":code,"decision":"WATCH","score":score,"confidence":"LOW",
        "reason_codes":["CAPITAL_EVIDENCE_LIMITED","SECTOR_RISK_NOT_SOURCE_BOUND"],
        "zone_low_anchor":"NONE","zone_high_anchor":"NONE","zone_thesis_code":"WITHHOLD"
    }


def test_buy_anchor_contract_validates_and_resolves_without_entry_v1():
    s=source();r=run056.validate_model_row(buy_row(),s,SCOPE)
    p=run056.public_row(r,s,0,"a"*64)
    assert p["formal_action"] == "BUY"
    assert p["zone_status"] == "APPROVED_NUMERIC"
    assert p["zone_lower_hkd"] == 98.0
    assert p["zone_upper_hkd"] == 101.0
    assert p["entry_v1_applied"] is False
    assert p["execution_quote_used"] is False
    assert p["order_created"] is False and p["fill_created"] is False


def test_nonbuy_cannot_smuggle_numeric_zone():
    s=source();r=watch_row();r["zone_low_anchor"]="PRIOR_MA10"
    with pytest.raises(ValueError, match="RUN056_NONBUY_ZONE_MUST_WITHHOLD"):
        run056.validate_model_row(r,s,SCOPE)


def test_sector_missingness_must_survive():
    s=source();r=watch_row();r["reason_codes"]=["NO_EDGE","CAPITAL_EVIDENCE_LIMITED"]
    with pytest.raises(ValueError, match="RUN056_SECTOR_MISSINGNESS_DROPPED"):
        run056.validate_model_row(r,s,SCOPE)


def test_not_disclosed_capital_cannot_be_called_verified_accumulation():
    s=source(capital_state="NOT_DISCLOSED_IN_TOP10")
    r=buy_row();r["reason_codes"]=["CAPITAL_ACCUMULATION_VERIFIED","SUPPORT_HOLD","SECTOR_RISK_NOT_SOURCE_BOUND"]
    with pytest.raises(ValueError, match="RUN056_CAPITAL_INVENTED"):
        run056.validate_model_row(r,s,SCOPE)


def test_global_rank_does_not_force_three_buys():
    s1=source("00001");s2=source("00002");s3=source("00003")
    rows=[
        run056.public_row(run056.validate_model_row(buy_row("00001",88),s1,SCOPE),s1,0,"a"*64),
        run056.public_row(run056.validate_model_row(watch_row("00002",91),s2,SCOPE),s2,0,"b"*64),
        run056.public_row(run056.validate_model_row(watch_row("00003",70),s3,SCOPE),s3,1,"c"*64),
    ]
    out=run056.finalize(rows,"09618",{"x":"d"*64},[
        {"http_confirmed":1,"http_possible":1,"pre_send_upper_cny":"0.10","isolated_rows":[]},
        {"http_confirmed":1,"http_possible":1,"pre_send_upper_cny":"0.10","isolated_rows":[]},
    ])
    assert out["Top10"][0]["code"] == "00002"
    assert len(out["Top3"]) == 1
    assert out["Top3"][0]["code"] == "00001"
    assert out["qualified_BUY"] == 1
    assert out["macro_overlay"]["changes_native_score_or_rank"] is False


def test_buy_anchor_order_must_be_valid():
    s=source();r=buy_row();r["zone_low_anchor"]="CURRENT_CLOSE";r["zone_high_anchor"]="PRIOR_SUPPORT20"
    with pytest.raises(ValueError, match="RUN056_BUY_ZONE_ANCHOR_ORDER"):
        run056.validate_model_row(r,s,SCOPE)
