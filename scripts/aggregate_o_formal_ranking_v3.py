#!/usr/bin/env python3
"""Aggregate O v3 processed members into the formal core ranking.

No model/network access. Ranking reproduces the frozen original renderer's
primary ordering: sentiment_score descending with stable official-universe order
as the tie-break. Narrative quarantine does not alter strategy-core fields.
"""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path


def load(path:Path):
    return json.loads(path.read_text(encoding="utf-8"))


def universe_index(universe:dict):
    rows=universe.get("members") or []
    return {str(x["code"]):(i,x) for i,x in enumerate(rows)}


def extract_members(obj:dict):
    if isinstance(obj.get("members"),list):
        return obj["members"]
    if isinstance(obj.get("member_statuses"),list):
        return obj["member_statuses"]
    if isinstance(obj.get("ranking"),list):
        rows=[]
        for x in obj["ranking"]:
            rows.append({
              "code":x.get("code"),"status":"CORE_ACCEPTED","ranking_eligible":True,
              "strategy_core":{
                "sentiment_score":x.get("sentiment_score"),"action":x.get("action"),
                "decision_type":x.get("decision_type"),"action_family":x.get("action_family"),
              },
              "strategy_core_sha256":x.get("strategy_core_sha256"),
              "raw_result_sha256":x.get("raw_result_sha256"),
              "provider_response_sha256":x.get("provider_response_sha256"),
              "narrative_release_status":x.get("narrative_release_status"),
            })
        for x in obj.get("additional_exclusions") or []:
            rows.append({
              "code":x.get("code"),"status":x.get("status") or "EXPLICIT_EXCLUSION",
              "ranking_eligible":False,"failure_code":x.get("failure_code"),
            })
        return rows
    if obj.get("code") and "ranking_eligible" in obj:
        return [obj]
    return []


def aggregate(universe:dict,policy:dict,sources:list[tuple[str,dict]]):
    idx=universe_index(universe)
    cur=policy.get("current_session") or {}
    official=int(cur["official_denominator"])
    base_operational=int(cur["operational_denominator"])
    if len(idx)!=official:
        raise ValueError("OFFICIAL_UNIVERSE_COUNT_MISMATCH")
    base_excluded={str(x["code"]) for x in cur.get("excluded_unresolved") or []}
    expected=[code for code,(i,m) in sorted(idx.items(),key=lambda kv:kv[1][0]) if code not in base_excluded]
    if len(expected)!=base_operational:
        raise ValueError("BASE_OPERATIONAL_RECONCILIATION_FAILED")

    by_code={}
    provenance={}
    for source_name,obj in sources:
        for row in extract_members(obj):
            code=str(row.get("code") or "")
            if code not in idx:
                raise ValueError("ROW_OUTSIDE_OFFICIAL_UNIVERSE:"+code)
            if code in base_excluded:
                raise ValueError("ROW_FOR_BASE_EXCLUDED_CODE:"+code)
            if code in by_code:
                raise ValueError("DUPLICATE_PROCESSED_CODE:"+code)
            normalized=dict(row)
            normalized["universe_index"]=idx[code][0]
            by_code[code]=normalized
            provenance[code]=source_name

    unprocessed_statuses={"SKIPPED_AFTER_SHARED_STOP","SHARED_FAILURE_UNPROCESSED"}
    missing=[]
    accepted=[]
    explicit_excluded=[]
    shared_unprocessed=[]
    for code in expected:
        row=by_code.get(code)
        if row is None:
            missing.append(code)
            continue
        if row.get("status") in unprocessed_statuses:
            missing.append(code)
            shared_unprocessed.append({
              "code":code,"status":row.get("status"),"failure_code":row.get("failure_code"),
              "source":provenance[code],
            })
            continue
        if row.get("ranking_eligible") is True:
            core=row.get("strategy_core") or {}
            score=core.get("sentiment_score")
            if isinstance(score,bool) or not isinstance(score,(int,float)) or not (0<=float(score)<=100):
                raise ValueError("INVALID_ACCEPTED_SCORE:"+code)
            action=str(core.get("action") or "").strip().lower()
            if not action:
                raise ValueError("MISSING_ACCEPTED_ACTION:"+code)
            accepted.append({
              "code":code,
              "name":idx[code][1].get("official_name"),
              "universe_index":idx[code][0],
              "sentiment_score":score,
              "action":action,
              "decision_type":core.get("decision_type"),
              "action_family":core.get("action_family"),
              "narrative_release_status":row.get("narrative_release_status"),
              "strategy_core_sha256":row.get("strategy_core_sha256"),
              "raw_result_sha256":row.get("raw_result_sha256"),
              "provider_response_sha256":row.get("provider_response_sha256"),
              "source":provenance[code],
            })
        else:
            explicit_excluded.append({
              "code":code,
              "name":idx[code][1].get("official_name"),
              "universe_index":idx[code][0],
              "status":row.get("status") or "NOT_RANKING_ELIGIBLE",
              "failure_code":row.get("failure_code"),
              "source":provenance[code],
            })

    accepted.sort(key=lambda x:(-float(x["sentiment_score"]),x["universe_index"]))
    for n,row in enumerate(accepted,1):
        row["rank"]=n
    top10=accepted[:10];top3=accepted[:3]
    complete=not missing
    if not complete:
        state="PARTIAL_O_FORMAL_CORE_PROCESSING"
    elif len(accepted)<3:
        state="NO_GO_TOO_FEW_RANKING_ELIGIBLE"
    else:
        state="PASS_O_FORMAL_CORE_RANKING_TOP3"
    status_counts=Counter(x["status"] for x in explicit_excluded)
    return {
      "schema_version":1,
      "state":state,
      "target_session":cur.get("session"),
      "official_O_denominator":official,
      "base_operational_O_denominator":base_operational,
      "base_excluded_unresolved":sorted(base_excluded,key=lambda c:idx[c][0]),
      "base_excluded_count":len(base_excluded),
      "processed_operational_members":len(accepted)+len(explicit_excluded),
      "rows_received":len(by_code),
      "missing_operational_members":missing,
      "missing_count":len(missing),
      "ranking_eligible_count":len(accepted),
      "additional_excluded_count":len(explicit_excluded),
      "shared_unprocessed_count":len(shared_unprocessed),
      "shared_unprocessed":shared_unprocessed,
      "additional_excluded_status_counts":dict(sorted(status_counts.items())),
      "reconciliation":{
        "official":official,
        "base_operational":base_operational,
        "base_excluded":len(base_excluded),
        "rows_received":len(by_code),
        "processed":len(accepted)+len(explicit_excluded),
        "missing":len(missing),
        "ranking_eligible":len(accepted),
        "additional_excluded":len(explicit_excluded),
        "official_equals_base_plus_excluded":base_operational+len(base_excluded)==official,
        "processed_plus_missing_equals_base":len(accepted)+len(explicit_excluded)+len(missing)==base_operational,
        "eligible_plus_additional_excluded_equals_processed":True,
      },
      "formal_O_ranking_generated":state=="PASS_O_FORMAL_CORE_RANKING_TOP3",
      "formal_signal_generated":False,
      "ranking":accepted,
      "Top3":top3,
      "Top10":top10,
      "qualified_buy_in_Top3":sum(x.get("action_family")=="buy" for x in top3),
      "execution_signal_generated":False,
      "real_orders":0,
      "simulation_writes":0,
      "ranking_contract":{
        "primary_key":"sentiment_score_desc",
        "tie_break":"official_universe_order_asc",
        "narrative_quarantine_changes_score_or_action":False,
      },
      "additional_exclusions":explicit_excluded,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--source",type=Path,action="append",required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    sources=[(str(p),load(p)) for p in a.source]
    out=aggregate(load(a.universe),load(a.policy),sources)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "state":out["state"],"processed":out["processed_operational_members"],
      "eligible":out["ranking_eligible_count"],"missing":out["missing_count"],
      "top3":[[x["code"],x["sentiment_score"],x["action"]] for x in out["Top3"]],
    },ensure_ascii=False))


if __name__=="__main__":
    main()
