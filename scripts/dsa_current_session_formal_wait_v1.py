#!/usr/bin/env python3
"""Formalize one current-session O/U WAIT authority from immutable evidence.

This is deterministic and deliberately cannot invent a BUY or a current-session
ranking. It turns a verified no-current-session-signal state into explicit,
session-correct Formal WAIT receipts.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

O_WAIT = "PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING"
U_WAIT = "PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT:" + str(path))
    return value


def build(e: dict, target: str) -> tuple[dict, dict, dict]:
    if e.get("target_session") != target:
        raise ValueError("EVIDENCE_TARGET_SESSION_MISMATCH")
    if (e.get("safety") or {}).get("real_orders") != 0:
        raise ValueError("REAL_ORDERS_NONZERO")
    if (e.get("safety") or {}).get("model_http_requests_confirmed") != 0:
        raise ValueError("MODEL_CALLS_NONZERO_FOR_DETERMINISTIC_FORMALIZER")

    o=e.get("O") or {}; u=e.get("U") or {}
    for track,block in (("O",o),("U",u)):
        for phase in ("preopen","close"):
            row=block.get(phase) or {}
            if int(row.get("current_session_formal_signals",-1)) != 0:
                raise ValueError(track+"_CURRENT_SESSION_FORMAL_SIGNAL_NONZERO")
            if row.get("latest_accepted_target_session") == target:
                raise ValueError(track+"_EVIDENCE_ALREADY_HAS_CURRENT_FORMAL_SIGNAL")
            if int(row.get("latest_qualified_BUY",-1)) != 0:
                raise ValueError(track+"_LATEST_QUALIFIED_BUY_NONZERO")

    if int((o.get("close") or {}).get("official_denominator",-1)) != 660:
        raise ValueError("O_OFFICIAL_DENOMINATOR_NOT_660")
    if int((o.get("close") or {}).get("operational_denominator",-1)) != 657:
        raise ValueError("O_OPERATIONAL_DENOMINATOR_NOT_657")
    if int((u.get("close") or {}).get("denominator",-1)) != 45:
        raise ValueError("U_DENOMINATOR_NOT_45")

    blockers=list((u.get("preopen") or {}).get("current_session_blockers") or [])
    expected={
      "U_CURRENT_SESSION_MACRO_CAP_MISSING",
      "U_CURRENT_SESSION_RISK_EVIDENCE_MISSING",
      "U_CURRENT_SESSION_ZONE_CONTRACT_MISSING",
    }
    if set(blockers) != expected:
        raise ValueError("U_CURRENT_SESSION_BLOCKERS_MISMATCH")

    source=e.get("source") or {}
    provenance={
      "repository":source.get("repository"),
      "branch":source.get("branch"),
      "journal_path":source.get("journal_path"),
      "journal_blob_sha":source.get("journal_blob_sha"),
    }

    o_receipt={
      "schema_version":1,
      "run_id":"DSA-O-PROD-"+target.replace("-","")+"-CURRENT-WAIT",
      "target_session":target,
      "track":"O",
      "status":O_WAIT,
      "official_O_denominator":660,
      "operational_O_denominator":657,
      "current_session_formal_signals":0,
      "qualified_buy_in_Top3":0,
      "Top3":[],
      "Top10":[],
      "provider_skipped":True,
      "execution_signal_generated":False,
      "entry_v1_handoff":False,
      "wait_reason":"O_CURRENT_SESSION_FORMAL_RANKING_MISSING",
      "prior_reference":o.get("prior_reference"),
      "evidence":{
        **provenance,
        "preopen_command_id":o["preopen"]["command_id"],
        "preopen_wrapper_hash":o["preopen"]["wrapper_hash"],
        "close_command_id":o["close"]["command_id"],
        "close_wrapper_hash":o["close"]["wrapper_hash"],
        "close_available_at":o["close"]["at"],
      },
      "resource_accounting":{
        "model_http_requests_confirmed":0,
        "real_orders":0,
        "simulation_writes":0,
        "auto_recharge":False,
      },
    }

    u_receipt={
      "schema_version":1,
      "run_id":"DSA-U-PROD-"+target.replace("-","")+"-CURRENT-WAIT",
      "target_session":target,
      "track":"U",
      "state":U_WAIT,
      "denominator":45,
      "eligible":None,
      "formal_valid_rows":0,
      "current_session_formal_signals":0,
      "qualified_BUY":0,
      "Top3":[],
      "Top10":[],
      "rows":[],
      "prerequisite_blockers":blockers,
      "provider_skipped":True,
      "buyable_verified_count":0,
      "entry_v1_handoff":False,
      "prior_reference":u.get("prior_reference"),
      "evidence":{
        **provenance,
        "preopen_command_id":u["preopen"]["command_id"],
        "preopen_wrapper_hash":u["preopen"]["wrapper_hash"],
        "close_command_id":u["close"]["command_id"],
        "close_wrapper_hash":u["close"]["wrapper_hash"],
        "close_available_at":u["close"]["at"],
      },
      "resource_accounting":{
        "model_http_requests_confirmed":0,
        "real_orders":0,
        "simulation_writes":0,
        "auto_recharge":False,
      },
    }

    acceptance={
      "schema_version":1,
      "acceptance_id":"DSA-FORMAL-CURRENT-SESSION-"+target.replace("-","")+"-WAIT-001",
      "target_session":target,
      "status":"ACCEPTED_CURRENT_SESSION_FORMAL_WAIT",
      "O_status":O_WAIT,
      "U_state":U_WAIT,
      "O_current_session":True,
      "U_current_session":True,
      "qualified_buy_total":0,
      "formal_wait_is_authoritative_for_target_session":True,
      "prior_session_rankings_not_relabelled":True,
      "source_foundation_journal":provenance,
      "source_command_hashes":{
        "O_preopen":o["preopen"]["wrapper_hash"],
        "O_close":o["close"]["wrapper_hash"],
        "U_preopen":u["preopen"]["wrapper_hash"],
        "U_close":u["close"]["wrapper_hash"],
      },
      "resource_accounting":{
        "model_http_requests_confirmed":0,
        "paid_data_calls":0,
        "real_orders":0,
        "simulation_writes":0,
        "auto_recharge":False,
      },
    }
    return o_receipt,u_receipt,acceptance


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--o-out",type=Path,required=True)
    ap.add_argument("--u-out",type=Path,required=True)
    ap.add_argument("--acceptance-out",type=Path,required=True)
    a=ap.parse_args()
    o,u,acc=build(load(a.evidence),a.target_session)
    for path,value in ((a.o_out,o),(a.u_out,u),(a.acceptance_out,acc)):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":acc["status"],"target_session":a.target_session,"qualified_buy_total":0,"real_orders":0}))


if __name__=="__main__":
    main()
