#!/usr/bin/env python3
"""Read-only DSA Production Orchestrator candidate adapter v1.

Consumes:
- ACTIVE Foundation runtime journal + derived summary;
- accepted formal O/U receipts from the DSA candidate tree.

Produces one comparison receipt only. It never imports or accesses the candidate
Drive journal, never writes an account, and never calls a model/data/broker API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def canonical_hash(obj: object) -> str:
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_authority_pair(journal: dict, summary: dict) -> dict:
    if canonical_hash(journal.get("config")) != journal.get("config_hash"):
        raise ValueError("ACTIVE_CONFIG_HASH_MISMATCH")
    parent=journal["config_hash"]
    ids=set()
    by={"O":0,"U":0}
    for item in journal.get("commands") or []:
        if item.get("parent") != parent:
            raise ValueError("ACTIVE_PARENT_CHAIN_MISMATCH")
        cmd=item.get("command")
        if not isinstance(cmd,dict):
            raise ValueError("ACTIVE_COMMAND_INVALID")
        cid=str(cmd.get("id") or "")
        if not cid or cid in ids:
            raise ValueError("ACTIVE_COMMAND_ID_INVALID")
        if item.get("hash") != canonical_hash({"parent":parent,"command":cmd}):
            raise ValueError("ACTIVE_COMMAND_HASH_MISMATCH")
        ids.add(cid);parent=item["hash"]
        if cmd.get("account") in by:
            by[cmd["account"]]+=1
    jh=canonical_hash(journal)
    if summary.get("journal_hash") != jh:
        raise ValueError("ACTIVE_SUMMARY_JOURNAL_HASH_MISMATCH")
    return {
        "journal_canonical_hash":jh,
        "command_count":len(journal.get("commands") or []),
        "last_command_hash":parent,
        "commands_by_account":by,
        "summary_matches_journal":True,
    }


def latest_active_signal(journal: dict, account: str, target_session: str) -> dict:
    latest=None
    for item in journal.get("commands") or []:
        cmd=item.get("command") or {}
        sig=cmd.get("signal") or {}
        if cmd.get("account") != account or cmd.get("kind") != "SIGNAL":
            continue
        identity=" ".join([
            str(cmd.get("id") or ""),
            str(sig.get("id") or ""),
            str(sig.get("cutoff") or ""),
            str(sig.get("available_at") or ""),
        ])
        if target_session in identity:
            latest=cmd
    if latest is None:
        raise ValueError(f"ACTIVE_{account}_TARGET_SIGNAL_MISSING")
    sig=latest.get("signal") or {}
    return {
        "command_id":latest.get("id"),
        "signal_id":sig.get("id"),
        "reason":sig.get("reason"),
        "passed":bool(sig.get("passed")),
        "semantic_action":"BUY" if bool(sig.get("passed")) else "NO_BUY",
    }


def run(candidate_root: Path, authority_root: Path, target_session: str,
        at_hkt: str, next_session: str) -> dict:
    scripts=candidate_root/"scripts"
    sys.path.insert(0,str(scripts))
    from dsa_production_orchestrator_v1 import orchestrate

    runtime=json.loads((authority_root/"control_room/dsa/runtime/RUNTIME_STATE.json").read_text())
    if runtime.get("runtime_activated") is not True or runtime.get("shadow_simulation_only") is not True:
        raise ValueError("ACTIVE_RUNTIME_NOT_SHADOW_ACTIVE")
    if runtime.get("real_orders_authorized") is not False:
        raise ValueError("ACTIVE_REAL_ORDER_BOUNDARY_BREACH")

    jp=authority_root/"control_room/dsa/runtime/authority/DSA_DUAL_ACCOUNT_JOURNAL.json"
    sp=authority_root/"control_room/dsa/runtime/authority/DSA_DUAL_ACCOUNT_SUMMARY.json"
    journal=json.loads(jp.read_text());summary=json.loads(sp.read_text())
    pair=validate_authority_pair(journal,summary)

    op=candidate_root/"docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json"
    up=candidate_root/"docs/runtime/U_PRODUCTION_FORMAL_LATEST.json"
    o=json.loads(op.read_text());u=json.loads(up.read_text())
    if o.get("target_session") != target_session or u.get("target_session") != target_session:
        raise ValueError("FORMAL_RECEIPT_SESSION_MISMATCH")

    candidate=orchestrate(
        o,u,target_session,at_hkt,next_session,op,up,
        entry=None,journal_configured=False,cycle="postclose"
    )
    if any(int(candidate.get(k,0) or 0) != 0 for k in ("model_http_requests","broker_orders","real_orders")):
        raise ValueError("CANDIDATE_EXTERNAL_ACTION_BOUNDARY_BREACH")

    active={a:latest_active_signal(journal,a,target_session) for a in ("O","U")}
    candidate_semantic={
        a:"BUY" if candidate["tracks"][a]["state"]=="QUALIFIED_BUY" else "NO_BUY"
        for a in ("O","U")
    }
    equivalent={a:(active[a]["semantic_action"]==candidate_semantic[a]) for a in ("O","U")}
    status="PASS_READ_ONLY_PARALLEL_SHADOW_REPLAY" if all(equivalent.values()) else "FAIL_DECISION_DIVERGENCE"
    return {
        "schema_version":"DSA_RUNTIME_CANDIDATE_READONLY_ADAPTER_v1",
        "status":status,
        "comparison_scope":"ENGINEERING_PARALLEL_SHADOW_REPLAY_NOT_NATURAL_FORWARD_WINDOW",
        "target_session":target_session,
        "evaluation_time_hkt":at_hkt,
        "next_session":next_session,
        "active_runtime":{
            "contract_id":runtime.get("contract_id"),
            "runtime_activated":runtime.get("runtime_activated"),
            "shadow_simulation_only":runtime.get("shadow_simulation_only"),
            "journal_raw_sha256":raw_sha256(jp),
            "summary_raw_sha256":raw_sha256(sp),
            **pair,
            "tracks":active,
        },
        "candidate":{
            "version":candidate.get("version"),
            "state":candidate.get("state"),
            "qualified_buy_total":candidate.get("qualified_buy_total"),
            "tracks":{a:{
                "state":candidate["tracks"][a]["state"],
                "qualified_buy":candidate["tracks"][a]["qualified_buy"],
                "blockers":candidate["tracks"][a]["blockers"],
                "semantic_action":candidate_semantic[a],
            } for a in ("O","U")},
            "generated_commands_not_persisted":len(candidate.get("commands") or []),
            "model_http_requests":candidate.get("model_http_requests",0),
            "broker_orders":candidate.get("broker_orders",0),
            "real_orders":candidate.get("real_orders",0),
        },
        "decision_equivalence":equivalent,
        "candidate_drive_journal_accessed":False,
        "active_journal_write_attempts":0,
        "candidate_journal_write_attempts":0,
        "dashboard_writes":0,
        "model_http_requests":0,
        "paid_data_calls":0,
        "broker_calls":0,
        "real_orders":0,
        "authority_switch_performed":False,
        "migration_interpretation":"Engineering replay may qualify candidate read-only compatibility only; it does not satisfy a future natural parallel window or authorize cutover.",
    }


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidate-root",type=Path,required=True)
    ap.add_argument("--authority-root",type=Path,required=True)
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--at-hkt",required=True)
    ap.add_argument("--next-session",required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    result=run(a.candidate_root,a.authority_root,a.target_session,a.at_hkt,a.next_session)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"decision_equivalence":result["decision_equivalence"],
                      "writes":result["active_journal_write_attempts"]+result["candidate_journal_write_attempts"],
                      "real_orders":result["real_orders"]},ensure_ascii=False))
    if not result["status"].startswith("PASS_"):
        raise SystemExit(2)


if __name__=="__main__":
    main()
