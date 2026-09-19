#!/usr/bin/env python3
"""Repair O657 final reconciliation after stale Run073 parent overwrite.

The authoritative Run073 run1 receipt is immutable at commit
37260f104c8522814d830df882f259c1eed88075. A later cancelled Run073 run2
overwrote the branch copy and reintroduced nine already-explicitly-excluded
members as missing. This repair is deterministic and model-free: it restores
only those nine exclusion rows from the authoritative parent snapshot into the
completed Run075 result, then closes the O657 reconciliation.

No ranking fields are recomputed from raw content and no model/provider access
is performed.
"""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path

GOOD_PARENT_COMMIT="37260f104c8522814d830df882f259c1eed88075"
EXPECTED_FAILURE="TARGET_SESSION_VOLUME_OUTSIDE_CALIBRATED_BOUND"
EXPECTED_STATUS="EXCLUDED_PREFLIGHT_NO_RESCUE"


def repair(run075:dict, good_parent:dict) -> dict:
    if run075.get("run_id")!="TRI-DSA-O-RECOVER-20260918-075":
        raise ValueError("RUN075_ID_MISMATCH")
    if run075.get("target_session")!="2026-09-18":
        raise ValueError("RUN075_SESSION_MISMATCH")
    if good_parent.get("run_id")!="TRI-DSA-O-CONT-20260918-073":
        raise ValueError("GOOD_PARENT_RUN_ID_MISMATCH")
    if good_parent.get("missing_count")!=101:
        raise ValueError("GOOD_PARENT_MISSING_COUNT_MISMATCH")
    missing=[str(x) for x in run075.get("missing_operational_members") or []]
    if len(missing)!=9 or len(set(missing))!=9:
        raise ValueError("RUN075_EXPECTED_NINE_MISSING")
    existing={str(x.get("code")) for x in run075.get("additional_exclusions") or []}
    parent_map={str(x.get("code")):x for x in good_parent.get("additional_exclusions") or []}
    recovered=[]
    for code in missing:
        if code in existing:
            raise ValueError("MISSING_ALREADY_IN_RUN075_EXCLUSIONS:"+code)
        row=parent_map.get(code)
        if not row:
            raise ValueError("MISSING_NOT_IN_AUTHORITATIVE_PARENT:"+code)
        if row.get("status")!=EXPECTED_STATUS:
            raise ValueError("AUTHORITATIVE_PARENT_STATUS_MISMATCH:"+code)
        if row.get("failure_code")!=EXPECTED_FAILURE:
            raise ValueError("AUTHORITATIVE_PARENT_FAILURE_MISMATCH:"+code)
        recovered.append(dict(row))

    out=json.loads(json.dumps(run075))
    out["run_id"]="TRI-DSA-O-FINAL-20260918-076"
    out["state"]="PASS_O_FORMAL_CORE_RANKING_TOP3"
    out["continuation_parent"]="docs/runtime/RUN075_O657_FORMAL_RESULT.json"
    out["parent_snapshot_repair"]={
      "authoritative_parent_commit":GOOD_PARENT_COMMIT,
      "polluted_branch_parent_rejected":True,
      "recovered_explicit_exclusion_count":len(recovered),
      "recovered_codes":[x["code"] for x in recovered],
      "recovered_status":EXPECTED_STATUS,
      "recovered_failure_code":EXPECTED_FAILURE,
      "model_http_requests_added":0,
      "provider_calls_added":0,
      "ranking_rows_changed":0,
    }
    out["additional_exclusions"]=(out.get("additional_exclusions") or [])+recovered
    out["additional_exclusions"].sort(key=lambda x:int(x.get("universe_index",10**9)))
    out["missing_operational_members"]=[]
    out["missing_count"]=0
    out["shared_unprocessed"]=[]
    out["shared_unprocessed_count"]=0
    out["processed_operational_members"]=int(out["base_operational_O_denominator"])
    out["rows_received"]=int(out["base_operational_O_denominator"])
    out["additional_excluded_count"]=len(out["additional_exclusions"])
    if int(out["ranking_eligible_count"])+int(out["additional_excluded_count"])!=int(out["base_operational_O_denominator"]):
        raise ValueError("FINAL_OPERATIONAL_RECONCILIATION_FAILED")
    counts=Counter(x.get("status") or "UNKNOWN" for x in out["additional_exclusions"])
    out["additional_excluded_status_counts"]=dict(sorted(counts.items()))
    out["formal_O_ranking_generated"]=True
    out["formal_signal_generated"]=False
    out["execution_signal_generated"]=False
    out["real_orders"]=0
    out["simulation_writes"]=0
    rec=out.get("reconciliation") or {}
    rec.update({
      "official":int(out["official_O_denominator"]),
      "base_operational":int(out["base_operational_O_denominator"]),
      "base_excluded":int(out["base_excluded_count"]),
      "rows_received":int(out["base_operational_O_denominator"]),
      "processed":int(out["base_operational_O_denominator"]),
      "missing":0,
      "ranking_eligible":int(out["ranking_eligible_count"]),
      "additional_excluded":int(out["additional_excluded_count"]),
      "official_equals_base_plus_excluded":(
          int(out["base_operational_O_denominator"])+int(out["base_excluded_count"])
          == int(out["official_O_denominator"])
      ),
      "processed_plus_missing_equals_base":True,
      "eligible_plus_additional_excluded_equals_processed":True,
    })
    out["reconciliation"]=rec
    ranking=out.get("ranking") or []
    if len(ranking)!=int(out["ranking_eligible_count"]):
        raise ValueError("RANKING_COUNT_CHANGED_OR_INVALID")
    if (out.get("Top3") or [])!=ranking[:3]:
        raise ValueError("TOP3_NOT_RANKING_PREFIX")
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--run075",type=Path,required=True)
    ap.add_argument("--good-parent",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    out=repair(json.loads(a.run075.read_text()),json.loads(a.good_parent.read_text()))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({
      "state":out["state"],"processed":out["processed_operational_members"],
      "missing":out["missing_count"],"eligible":out["ranking_eligible_count"],
      "excluded":out["additional_excluded_count"],
      "top3":[[x["code"],x["sentiment_score"],x["action"]] for x in out["Top3"]],
    },ensure_ascii=False))


if __name__=="__main__":
    main()
