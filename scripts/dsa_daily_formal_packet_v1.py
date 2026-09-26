#!/usr/bin/env python3
"""Build session-dynamic O/U daily formal-generation packets.

No model/provider calls occur here. This module converts current-session frozen
inputs into the exact contracts consumed by the existing accepted O/U engines.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

FROZEN_UPSTREAM="089d9d26d68f8b839ea5a74a3784e4402925f8b7"

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def code(v)->str:
    s=str(v or "")
    if s.lower().startswith("hk"): s=s[2:]
    return s.zfill(5)

def market_session_for_decision(target:str, market_data_session:str|None=None)->str:
    """Keep the price date; a morning decision uses the previous XHKG close."""
    import exchange_calendars as xcals
    cal=xcals.get_calendar("XHKG")
    if not cal.is_session(target):
        raise ValueError("DECISION_SESSION_NOT_TRADING")
    market=market_data_session or target
    if market not in (target, cal.previous_session(target).date().isoformat()):
        raise ValueError("MARKET_SESSION_NOT_CURRENT_OR_PREVIOUS")
    return market

def build_o(universe:dict,coverage:dict,universe_sha:str,history_sha:str,target:str,
            market_data_session:str|None=None)->dict:
    market=market_session_for_decision(target,market_data_session)
    members=universe.get("members") or []
    if not universe.get("full_union_verified") or universe.get("effective_session")!=target:
        raise ValueError("O_CURRENT_OFFICIAL_UNIVERSE_NOT_VERIFIED")
    if len(members)!=int(universe.get("member_count",-1)):
        raise ValueError("O_UNIVERSE_COUNT_MISMATCH")
    rows=coverage.get("coverage") or []
    if coverage.get("expected_complete_session")!=market or len(rows)!=len(members):
        raise ValueError("O_COVERAGE_SESSION_OR_COUNT_MISMATCH")
    by={code(x.get("code")):x for x in rows}
    member_codes=[code(x.get("code")) for x in members]
    if len(by)!=len(rows) or set(by)!=set(member_codes):
        raise ValueError("O_COVERAGE_IDENTITY_MISMATCH")
    if any(r.get("status")=="current_valid_bar" and r.get("latest_date")!=market for r in rows):
        raise ValueError("O_COVERAGE_BAR_DATE_MISMATCH")
    excluded=[]
    for c in member_codes:
        r=by[c]
        if r.get("status")!="current_valid_bar":
            excluded.append({"code":c,"reason":r.get("status") or "missing",
                             "latest_date":r.get("latest_date"),"bars":r.get("bars")})
    official=len(members); operational=official-len(excluded)
    policy={
      "schema_version":1,"policy_id":"DSA-O-DAILY-UNRESOLVED-EXCLUSION-"+target,
      "status":"DAILY_SESSION_PACKET","effective_from_session":target,
      "principle":"Preserve official denominator; exclude bounded unresolved members from only the session operational ranking pool.",
      "current_session":{"session":target,"market_data_session":market,"official_denominator":official,
        "excluded_unresolved":excluded,"excluded_count":len(excluded),
        "operational_denominator":operational,"formal_O_denominator":operational},
      "boundaries":{"modifies_original_O_prompt_or_scoring":False,"model_calls_added":0,
        "main_merge":False,"real_orders":0}
    }
    ledger={
      "schema_version":1,"ledger_id":"DSA-O-DAILY-MODEL-LEDGER-"+target.replace("-",""),
      "session":target,"frozen_upstream":FROZEN_UPSTREAM,
      "policy":"No repeat per code/session/frozen upstream after a durable provider claim.",
      "confirmed_provider_sends":[],"no_repeat_uncertain_claims":[],
      "current_confirmed_send_count":0,"current_uncertain_no_repeat_count":0
    }
    scope={
      "schema_version":1,"run_id":"TRI-DSA-O-DAILY-"+target.replace("-",""),
      "target_session":target,"decision_session":target,"market_data_session":market,
      "official_O_denominator":official,"base_operational_O_denominator":operational,
      "frozen_upstream":FROZEN_UPSTREAM,
      "native_model_configuration":"O_DEEPSEEK_FLASH_NONTHINKING_v1",
      "current_universe_sha256":universe_sha,"history_cache_sha256":history_sha,
      "artifact_prefix":"ART-DSA-O-DAILY-"+target.replace("-",""),
      "per_member_hard_cap_cny":"0.10","per_member_authorized_ceiling_cny":"0.10",
      "balance_safety_reserve_cny":"0.50","max_shards":16,"max_parallel":4,
      "max_consecutive_provider_failures":2,"max_consecutive_infra_failures":2,
      "automatic_retry":False,"no_orders":True,"real_orders":0,"simulation_writes":0,"main_merge":False,
      "raw_content_public":False
    }
    return {"state":"READY_FOR_O_PROVIDER" if operational else "NO_OPERATIONAL_MEMBERS",
            "target_session":target,"market_data_session":market,"official_denominator":official,
            "operational_denominator":operational,"excluded_count":len(excluded),
            "policy":policy,"ledger":ledger,"scope":scope}

def build_u(close:dict,macro:dict,risk:dict,zone:dict,target:str)->dict:
    blockers=[]
    if close.get("target_session")!=target or int(close.get("denominator",-1))!=45:
        blockers.append("U_CLOSE_NOT_CURRENT")
    if int(close.get("current_valid_count",-1))!=45:
        blockers.append("U_CLOSE_NOT_45_OF_45")
    if macro.get("target_session")!=target or macro.get("result",{}).get("formal_macro_cap_available") is not True:
        blockers.append("U_MACRO_CAP_NOT_CURRENT")
    if risk.get("target_session")!=target or len(risk.get("rows") or [])!=45:
        blockers.append("U_RISK_EVIDENCE_NOT_CURRENT")
    if zone.get("target_session")!=target or len(zone.get("rows") or [])!=45:
        blockers.append("U_ZONE_CONTRACT_NOT_CURRENT")
    return {
      "schema_version":1,"target_session":target,
      "state":"READY_FOR_U_FORMAL_PROVIDER" if not blockers else "WAIT_U_PREREQUISITES",
      "blockers":blockers,"denominator":45,
      "provider_permitted":not blockers,"real_orders":0
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--o-universe",type=Path);ap.add_argument("--o-coverage",type=Path);ap.add_argument("--o-history",type=Path)
    ap.add_argument("--u-close",type=Path);ap.add_argument("--u-macro",type=Path);ap.add_argument("--u-risk",type=Path);ap.add_argument("--u-zone",type=Path)
    ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    out={"schema_version":1,"target_session":a.target_session}
    if a.o_universe:
        out["O"]=build_o(json.loads(a.o_universe.read_text()),json.loads(a.o_coverage.read_text()),
                         sha(a.o_universe),sha(a.o_history),a.target_session)
    if a.u_close:
        out["U"]=build_u(*(json.loads(p.read_text()) for p in (a.u_close,a.u_macro,a.u_risk,a.u_zone)),a.target_session)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:(v.get("state") if isinstance(v,dict) else v) for k,v in out.items() if k in ("O","U")}))
if __name__=="__main__":main()
