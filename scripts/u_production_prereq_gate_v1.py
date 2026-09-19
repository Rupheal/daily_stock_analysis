#!/usr/bin/env python3
"""Fail-closed U production prerequisite gate.

Determines whether the expensive formal U provider step may run for a target
session. Missing/stale prerequisites become a deterministic WAIT receipt;
nothing is silently carried forward across sessions.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

VERSION="U_PRODUCTION_PREREQ_GATE_v1"


def _target(obj): return obj.get("target_session")


def evaluate(target:str, close:dict, macro:dict|None, risk:dict|None, zone:dict|None, member:dict|None=None)->dict:
    blockers=[]
    if _target(close)!=target or close.get("denominator")!=45 or int(close.get("current_valid_count",-1))!=45:
        blockers.append("U_CLOSE_REFRESH_NOT_CURRENT_45_OF_45")
    member_ok=(
      isinstance(member,dict)
      and _target(member)==target
      and int(member.get("U_denominator",member.get("denominator",-1)))==45
      and len(member.get("members") or member.get("rows") or [])==45
    )
    if not member_ok: blockers.append("U_MEMBER_REPORTS_NOT_CURRENT")
    macro_ok=(
      isinstance(macro,dict)
      and _target(macro)==target
      and (macro.get("result") or {}).get("formal_macro_cap_available") is True
      and (macro.get("regime") or {}).get("position_ceiling_pct") is not None
    )
    if not macro_ok: blockers.append("U_MACRO_CAP_NOT_CURRENT")
    risk_ok=(
      isinstance(risk,dict) and _target(risk)==target
      and int((risk.get("counts") or {}).get("denominator",-1))==45
      and (risk.get("result") or {}).get("risk_evidence_bound") is True
    )
    if not risk_ok: blockers.append("U_RISK_EVIDENCE_NOT_CURRENT")
    zone_ok=(
      isinstance(zone,dict) and _target(zone)==target
      and int(zone.get("denominator",-1))==45
      and zone.get("state")=="PASS_CONTRACT_ONLY_FORMAL_MEMBER_ZONES_PENDING_RUN056"
    )
    if not zone_ok: blockers.append("U_ZONE_CONTRACT_NOT_CURRENT")
    ready=not blockers
    return {
      "schema_version":1,"version":VERSION,"target_session":target,
      "state":"READY_FOR_U_FORMAL_PROVIDER" if ready else "WAIT_PREREQUISITES_BLOCKED",
      "formal_provider_permitted":ready,
      "blockers":blockers,
      "fallback_formal_receipt":{
        "schema_version":1,
        "run_id":"DSA-U-PROD-"+target.replace("-","")+"-PREREQ-WAIT",
        "target_session":target,
        "track":"U",
        "state":"PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
        "denominator":45,
        "eligible":None,
        "formal_valid_rows":0,
        "qualified_BUY":0,
        "Top3":[],
        "Top10":[],
        "rows":[],
        "prerequisite_blockers":blockers,
        "provider_skipped":True,
        "buyable_verified_count":0,
        "entry_v1_handoff":False,
        "resource_accounting":{
          "model_http_requests_confirmed":0,"real_orders":0,
          "simulation_writes":0,"auto_recharge":False
        }
      } if not ready else None,
      "model_http_requests":0,"real_orders":0,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--close",type=Path,required=True)
    ap.add_argument("--macro",type=Path)
    ap.add_argument("--member",type=Path)
    ap.add_argument("--risk",type=Path)
    ap.add_argument("--zone",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--fallback-out",type=Path)
    a=ap.parse_args()
    load=lambda p: json.loads(p.read_text()) if p and p.exists() else None
    r=evaluate(a.target_session,load(a.close),load(a.macro),load(a.risk),load(a.zone),load(a.member))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    if r["fallback_formal_receipt"] and a.fallback_out:
        a.fallback_out.parent.mkdir(parents=True,exist_ok=True)
        a.fallback_out.write_text(json.dumps(r["fallback_formal_receipt"],ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"state":r["state"],"blockers":r["blockers"],"provider_permitted":r["formal_provider_permitted"]}))
if __name__=="__main__":main()
