#!/usr/bin/env python3
"""Build production close receipts and O operational policy for one HK session."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def build(o_universe,u_universe,o_cov,u_cov,target,o_u_sha,u_u_sha,o_h_sha,u_h_sha):
    om=o_universe.get("members") or [];um=u_universe.get("members") or []
    if len(om)!=int(o_universe.get("member_count",-1)) or not o_universe.get("full_union_verified"):
        raise ValueError("O_OFFICIAL_UNIVERSE_INVALID")
    if len(um)!=45 or int(u_universe.get("member_count",-1))!=45:
        raise ValueError("U45_UNIVERSE_INVALID")
    if o_universe.get("effective_session")!=target:
        raise ValueError("O_UNIVERSE_SESSION_MISMATCH")
    if (o_cov.get("expected_complete_session") or target)!=target or (u_cov.get("expected_complete_session") or target)!=target:
        raise ValueError("COVERAGE_SESSION_MISMATCH")
    oc=o_cov.get("coverage") or [];uc=u_cov.get("coverage") or []
    if len(oc)!=len(om) or len(uc)!=45:
        raise ValueError("COVERAGE_DENOMINATOR_MISMATCH")
    invalid=[]
    for x in oc:
        if x.get("status")!="current_valid_bar":
            code=str(x.get("code") or "").lower()
            if code.startswith("hk"):code=code[2:]
            invalid.append({"code":code.zfill(5),"reason":x.get("status") or "not_current",
                            "latest_date":x.get("latest_date"),"bars":x.get("bars",0)})
    o_ready=len(om)-len(invalid)
    u_ready=sum(x.get("status")=="current_valid_bar" for x in uc)
    policy={
      "schema_version":1,"policy_id":"DSA-O-PRODUCTION-UNRESOLVED-"+target.replace("-",""),
      "status":"ACTIVE_PRODUCTION_SESSION_POLICY","effective_from_session":target,
      "current_session":{
        "session":target,"official_denominator":len(om),"excluded_unresolved":invalid,
        "excluded_count":len(invalid),"operational_denominator":o_ready,
        "formal_O_denominator":o_ready,
        "reconciliation":f"{o_ready} operational + {len(invalid)} excluded unresolved = {len(om)} official"
      },
      "operational_universe":{
        "exclusion_blocks_formal_acceptance":False,
        "repeated_special_rescue_prohibited":True,
        "paid_model_calls_for_status_rescue":0,
        "reentry_rule":"Later normal session refresh only; no bespoke rescue."
      },
      "boundaries":{"real_orders":0,"main_merge":False}
    }
    receipt={
      "schema_version":1,"run_id":"DSA-PRODUCTION-CLOSE-"+target.replace("-",""),
      "target_session":target,"decision_session":target,
      "state":"CORE_DATA_REFRESH_PASS" if u_ready==45 and o_ready>0 else "CORE_DATA_REFRESH_PARTIAL",
      "official_O_denominator":len(om),"official_U_denominator":45,
      "O_current_valid":o_ready,"O_current_invalid":invalid,
      "U_current_valid":u_ready,
      "U_buy_eligible":sum(bool(x.get("channels")) for x in um),
      "O_universe_sha256":o_u_sha,"U_universe_sha256":u_u_sha,
      "O_market_history_sha256":o_h_sha,"U_market_history_sha256":u_h_sha,
      "model_http_requests":0,"DeepSeek_API_cost_cny":0,"real_orders":0,
      "simulation_writes":0,"formal_signal_generated":False,
      "next":"Run production O operational rollout and U prerequisite/formal pipeline."
    }
    return receipt,policy

def main():
    ap=argparse.ArgumentParser()
    for n in ("o-universe","u-universe","o-coverage","u-coverage","o-history","u-history"):
        ap.add_argument("--"+n,dest=n.replace("-","_"),type=Path,required=True)
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--receipt-out",type=Path,required=True);ap.add_argument("--policy-out",type=Path,required=True)
    a=ap.parse_args();load=lambda p:json.loads(p.read_text())
    receipt,policy=build(load(a.o_universe),load(a.u_universe),load(a.o_coverage),load(a.u_coverage),
                         a.target_session,sha(a.o_universe),sha(a.u_universe),sha(a.o_history),sha(a.u_history))
    a.receipt_out.parent.mkdir(parents=True,exist_ok=True);a.policy_out.parent.mkdir(parents=True,exist_ok=True)
    a.receipt_out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    a.policy_out.write_text(json.dumps(policy,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"target":a.target_session,"O":receipt["O_current_valid"],"O_den":receipt["official_O_denominator"],
                      "U":receipt["U_current_valid"],"excluded":len(receipt["O_current_invalid"])}))
if __name__=="__main__":main()
