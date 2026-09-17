import json
from pathlib import Path

from scripts.run054_u_risk_evidence import build_receipt


def test_run054_preserves_missingness_and_denominator():
    facts=[]
    reports=[]
    handoff=[]
    accepted=[]
    for i in range(45):
        code=f"{i+1:05d}"
        facts.append({"code":code,"official_name":code,"current_valid_bar":True,"close":10+i})
        if i != 2:
            reports.append({
                "code":code,
                "name":code,
                "news":{"retrieval_ready":True,"verified_source_urls":[]},
                "capital":{"status":"NOT_DISCLOSED_IN_TOP10","source_locator":"hkex","source_sha256":"abc","persistence":"ONE_SESSION_ONLY_NOT_A_TREND","ultimate_investor_identity":"NOT_PROVEN"},
            })
            accepted.append(code)
        handoff.append({
            "code":code,
            "name":code,
            "current_buy_eligible": i != 2,
            "reviewed_issuer_primary_evidence":False,
            "primary_review_scope":None,
            "full_risk_coverage_proven":False,
        })
    receipt=build_receipt(
        close_refresh={"run_id":"r49","target_session":"2026-09-17","facts":facts},
        member_reports={"run_id":"r41","members":reports},
        handoff={"run_id":"r47","rows":handoff},
        review_acceptance={"run_id":"r46","accepted_codes":accepted,"isolated":[],"ineligible_codes":["00003"]},
        macro_cap={"run_id":"r53","target_session":"2026-09-17","regime":{"position_ceiling_pct":30}},
    )
    assert receipt["counts"]["denominator"] == 45
    assert receipt["counts"]["eligible"] == 44
    assert receipt["counts"]["ineligible_retained"] == 1
    assert receipt["counts"]["formal_decision_input_pass_with_missingness"] == 44
    assert receipt["result"]["risk_evidence_bound"] is True
    assert receipt["result"]["risk_evidence_complete_for_all_members"] is False
    assert receipt["result"]["qualified_BUY_created"] == 0
    assert all(r["sector_risk_evidence"]["state"] == "NOT_SEPARATELY_SOURCE_BOUND" for r in receipt["rows"])
