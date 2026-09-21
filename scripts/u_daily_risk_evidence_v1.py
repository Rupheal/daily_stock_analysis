#!/usr/bin/env python3
"""Build current-session U45 risk/capital evidence without stale handoff reuse."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def idx(rows): return {str(x.get("code") or "").zfill(5):x for x in rows}

def build(universe:dict,member:dict,capital:dict,macro:dict,target:str)->dict:
    members=universe.get("members") or []
    reports=idx(member.get("members") or [])
    if len(members)!=45 or len({str(x.get("code")).zfill(5) for x in members})!=45:
        raise ValueError("U45_UNIVERSE_INVALID")
    if member.get("target_session")!=target or macro.get("target_session")!=target:
        raise ValueError("U_CURRENT_SESSION_MISMATCH")
    if macro.get("result",{}).get("formal_macro_cap_available") is not True:
        raise ValueError("U_MACRO_CAP_NOT_FORMAL")
    cap=float(macro.get("regime",{}).get("position_ceiling_pct"))
    top=((capital.get("sources") or [{}])[0].get("data") or {}).get("top10_union") or {}
    rows=[]
    counts={"denominator":45,"eligible":0,"ineligible_retained":0,"current_bar_valid":0,
            "capital_verified":0,"capital_not_disclosed_in_top10":0,
            "formal_decision_input_pass_with_missingness":0}
    for m in members:
        code=str(m.get("code") or "").zfill(5)
        r=reports.get(code)
        eligible=bool(m.get("channels")) and m.get("execution_eligibility")!="not_in_verified_current_southbound_buy_sell_union"
        if eligible: counts["eligible"]+=1
        else: counts["ineligible_retained"]+=1
        valid=bool(r and r.get("data_session")==target and r.get("status")=="PRODUCTION_TECHNICAL_FACT_REPORT")
        counts["current_bar_valid"]+=int(valid)
        c=top.get(code) or {}
        cstatus="VERIFIED" if c.get("status")=="VERIFIED" else "NOT_DISCLOSED_IN_TOP10"
        counts["capital_verified"]+=int(cstatus=="VERIFIED")
        counts["capital_not_disclosed_in_top10"]+=int(cstatus!="VERIFIED")
        formal="PASS_WITH_EXPLICIT_RISK_MISSINGNESS" if eligible and valid else (
          "INELIGIBLE_RETAINED_NO_FORMAL_BUY_DECISION" if not eligible else "FAIL_CLOSED_INPUT_INCOMPLETE")
        counts["formal_decision_input_pass_with_missingness"]+=int(formal=="PASS_WITH_EXPLICIT_RISK_MISSINGNESS")
        rows.append({
          "code":code,"name":m.get("official_name") or m.get("user_alias"),
          "eligible":eligible,
          "current_close":((r or {}).get("facts") or {}).get("close"),
          "current_bar_valid":valid,
          "member_report_available":r is not None,
          "company_event_evidence":{
            "state":"CURRENT_SESSION_NEWS_NOT_FORMALLY_CLASSIFIED",
            "retrieval_ready":False,"verified_source_urls":[],
            "bounded_scope":"No stale issuer-event claim carried forward."
          },
          "capital_evidence":{
            "state":cstatus,"net_buy_hkd":c.get("net_buy_hkd"),
            "channel_coverage":c.get("channel_coverage"),
            "date":target,"persistence":"CURRENT_SESSION_ONLY",
            "ultimate_investor_identity":"NOT_PROVEN"
          },
          "issuer_primary_review":{
            "reviewed":False,"scope":"CURRENT_SESSION_NOT_SEPARATELY_REVIEWED",
            "full_risk_coverage_proven":False
          },
          "sector_risk_evidence":{
            "state":"NOT_SEPARATELY_SOURCE_BOUND",
            "rule":"Do not infer sector risk from price action or unsourced prose."
          },
          "qualitative_review":{"state":"CURRENT_SESSION_FORMAL_PROVIDER_MUST_JUDGE_WITH_MISSINGNESS",
                                "is_full_strategy_decision":False},
          "formal_decision_input_status":formal,
          "buy_permission_from_risk_layer":False
        })
    return {
      "schema_version":1,"run_id":"DSA-U-DAILY-RISK-"+target.replace("-",""),
      "target_session":target,
      "scope":"Current-session U45 price/technical + verified Southbound top10 capital evidence + explicit risk missingness.",
      "macro_position_ceiling_pct":cap,
      "counts":counts,"rows":rows,
      "result":{"status":"PASS_CURRENT_SESSION_RISK_PACKET_WITH_EXPLICIT_MISSINGNESS",
                "risk_evidence_complete_for_all_members":False,
                "qualified_BUY_created":0,"ranking_created":False},
      "resources":{"model_http_requests":0,"paid_data_calls":0,"real_orders":0}
    }

def main():
    ap=argparse.ArgumentParser()
    for x in ("universe","member","capital","macro","out"): ap.add_argument("--"+x,type=Path,required=True)
    ap.add_argument("--target-session",required=True)
    a=ap.parse_args()
    out=build(*(json.loads(getattr(a,x).read_text()) for x in ("universe","member","capital","macro")),a.target_session)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":out["result"]["status"],"counts":out["counts"]},ensure_ascii=False))
if __name__=="__main__":main()
