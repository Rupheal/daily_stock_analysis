import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run056_u_formal_decision_v2.py"
spec = importlib.util.spec_from_file_location("run056v2", MODULE_PATH)
run056v2 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(run056v2)


def test_ineligible_09618_can_remain_without_fabricated_prior_price_anchor():
    codes=[f"{i:05d}" for i in range(1,45)]+["09618"]
    members=[]; closes=[]; risks=[]; zones=[]
    for code in codes:
        eligible=code!="09618"
        facts={
            "close":100.0 if eligible else None,
            "volume_shares":1000.0 if eligible else None,
            "observed_support20":90.0 if eligible else None,
            "observed_resistance20":110.0 if eligible else None,
            "ma5":99.0 if eligible else None,
            "ma10":98.0 if eligible else None,
            "ma20":97.0 if eligible else None,
            "return_1d_pct":1.0 if eligible else None,
            "return_5d_pct":2.0 if eligible else None,
            "return_20d_pct":3.0 if eligible else None,
            "rsi14":55.0 if eligible else None,
            "macd":{"histogram_2x":0.5} if eligible else None,
            "volume_vs_previous5":1.1 if eligible else None,
            "trend":"BULLISH_MA_ORDER" if eligible else None,
        }
        members.append({"code":code,"name":code,"data_session":"2026-09-16","facts":facts})
        closes.append({"code":code,"open":100.0,"high":102.0,"low":99.0,"close":101.0,"volume":1200.0})
        risks.append({
            "code":code,"name":code,"eligible":eligible,
            "capital_evidence":{"state":"NOT_DISCLOSED_IN_TOP10","date":"2026-09-16","persistence":"ONE_SESSION_ONLY_NOT_A_TREND"},
            "company_event_evidence":{"state":"NO_VERIFIED_RECENT_EVENT_IN_BOUNDED_SEARCH_NOT_NO_RISK"},
            "issuer_primary_review":{"reviewed":False,"full_risk_coverage_proven":False},
            "sector_risk_evidence":{"state":"NOT_SEPARATELY_SOURCE_BOUND"},
            "qualitative_review":{"state":"RAW_SEMANTIC_PASS"},
        })
        zones.append({"code":code,"eligible":eligible,"zone_status":"PENDING_FORMAL_DECISION" if eligible else "WITHHELD_UNKNOWN","risk_missingness_explicit":True,"reason":"INELIGIBLE" if not eligible else "FORMAL_STRATEGY_DECISION_REQUIRED"})
    rows=run056v2.make_member_inputs(
        {"members":members},
        {"facts":closes},
        {"rows":risks},
        {"rows":zones},
    )
    assert len(rows)==45
    eligible=[x for x in rows if x["eligible"]]
    assert len(eligible)==44
    jd=[x for x in rows if x["code"]=="09618"][0]
    assert jd["eligible"] is False
    assert jd["allowed_zone_anchors"]=={}
    assert jd["current_return_from_prior_close_pct"] is None
    assert jd["retained_ineligible_reason"]=="INELIGIBLE"
