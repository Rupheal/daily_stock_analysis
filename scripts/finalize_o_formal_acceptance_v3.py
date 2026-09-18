#!/usr/bin/env python3
"""Finalize O formal acceptance from a completed v3 ranking receipt.

No model/network access. This is the last deterministic gate from formal core
ranking to an accepted O Top3 artifact.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

PASS_STATE="PASS_O_FORMAL_CORE_RANKING_TOP3"

def finalize(result:dict, policy:dict) -> dict:
    cur=policy.get("current_session") or {}
    blockers=[]
    if result.get("state")!=PASS_STATE:
        blockers.append("FORMAL_RANKING_STATE_NOT_PASS")
    if int(result.get("official_O_denominator",-1))!=int(cur.get("official_denominator",-2)):
        blockers.append("OFFICIAL_DENOMINATOR_MISMATCH")
    if int(result.get("base_operational_O_denominator",-1))!=int(cur.get("operational_denominator",-2)):
        blockers.append("OPERATIONAL_DENOMINATOR_MISMATCH")
    if int(result.get("missing_count",-1))!=0:
        blockers.append("MISSING_OPERATIONAL_MEMBERS")
    if result.get("formal_O_ranking_generated") is not True:
        blockers.append("FORMAL_RANKING_NOT_GENERATED")
    if result.get("formal_signal_generated") is not False:
        blockers.append("RANKING_ARTIFACT_MUST_NOT_IMPLY_EXECUTION_SIGNAL")
    top3=result.get("Top3") or []
    if len(top3)!=3:
        blockers.append("TOP3_LENGTH_NOT_3")
    ranking=result.get("ranking") or []
    if len(ranking)!=int(result.get("ranking_eligible_count",-1)):
        blockers.append("RANKING_COUNT_MISMATCH")
    ranks=[x.get("rank") for x in ranking]
    if ranks!=list(range(1,len(ranking)+1)):
        blockers.append("RANK_SEQUENCE_INVALID")
    if ranking[:3]!=top3:
        blockers.append("TOP3_NOT_RANKING_PREFIX")
    if int(result.get("real_orders",0) or 0)!=0 or int(result.get("simulation_writes",0) or 0)!=0:
        blockers.append("ORDER_OR_SIMULATION_SIDE_EFFECT")
    rec=result.get("reconciliation") or {}
    if rec.get("official_equals_base_plus_excluded") is not True:
        blockers.append("OFFICIAL_RECONCILIATION_FAILED")
    if rec.get("processed_plus_missing_equals_base") is not True:
        blockers.append("OPERATIONAL_RECONCILIATION_FAILED")
    accepted=not blockers
    return {
      "schema_version":1,
      "acceptance_version":"O_FORMAL_ACCEPTANCE_v3",
      "status":"ACCEPTED_O_FORMAL_TOP3" if accepted else "NOT_ACCEPTED",
      "target_session":result.get("target_session"),
      "source_run_id":result.get("run_id"),
      "source_state":result.get("state"),
      "official_O_denominator":result.get("official_O_denominator"),
      "operational_O_denominator":result.get("base_operational_O_denominator"),
      "ranking_eligible_count":result.get("ranking_eligible_count"),
      "base_excluded_count":result.get("base_excluded_count"),
      "additional_excluded_count":result.get("additional_excluded_count"),
      "missing_count":result.get("missing_count"),
      "Top3":top3 if accepted else [],
      "Top10":(result.get("Top10") or []) if accepted else [],
      "qualified_buy_in_Top3":result.get("qualified_buy_in_Top3") if accepted else None,
      "ranking_contract":result.get("ranking_contract"),
      "blockers":blockers,
      "execution_signal_generated":False,
      "real_orders":0,
      "simulation_writes":0,
      "raw_content_public":False,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--result",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    out=finalize(json.loads(a.result.read_text()),json.loads(a.policy.read_text()))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":out["status"],"source_run_id":out["source_run_id"],
                      "missing":out["missing_count"],
                      "top3":[[x.get("code"),x.get("sentiment_score"),x.get("action")] for x in out["Top3"]],
                      "blockers":out["blockers"]},ensure_ascii=False))
    if out["status"]!="ACCEPTED_O_FORMAL_TOP3":
        raise SystemExit(2)

if __name__=="__main__":
    main()
