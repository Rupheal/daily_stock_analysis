#!/usr/bin/env python3
"""DSA Production Orchestrator v1 core.

Deterministic production-control layer for O/U forward simulation.
It never places real orders and never invents price/FX/fees/board-lot evidence.

Responsibilities:
- validate O/U formal decision receipts against a target HK session;
- classify WAIT / QUALIFIED_BUY / STALE / BLOCKED independently per track;
- build immutable simulation SIGNAL commands;
- build ENTRY commands only from separately verified Entry-v1 evidence;
- fail closed when the authoritative simulation journal/config is unavailable.

This module performs no model, broker, or network calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

O_UPSTREAM="089d9d26d68f8b839ea5a74a3784e4402925f8b7"
VERSION="DSA_PRODUCTION_ORCHESTRATOR_v1"


def sha256_bytes(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def iso_at(value:str)->str:
    # Fail closed on naive timestamps.
    d=datetime.fromisoformat(value.replace("Z","+00:00"))
    if d.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return d.isoformat()


def norm_action(value)->str:
    return str(value or "").strip().upper()


def evidence(path:Path)->dict:
    data=path.read_bytes()
    return {"verified":True,"source":str(path),"sha256":sha256_bytes(data)}


def _o_candidates(receipt:dict)->list[dict]:
    rows=[]
    for x in receipt.get("Top3") or []:
        action=norm_action(x.get("action"))
        family=str(x.get("action_family") or "").lower()
        buy=(action=="BUY" or family=="buy")
        rows.append({
          "code":str(x.get("code") or ""),
          "name":x.get("name"),
          "rank":x.get("rank"),
          "score":x.get("sentiment_score"),
          "industry":x.get("industry"),
          "action":"BUY" if buy else action,
          "buyable_verified":bool(x.get("buyable_verified")) if buy else False,
          "source_row":x,
        })
    return rows


def _u_candidates(receipt:dict)->list[dict]:
    by_code={str(x.get("code")):x for x in receipt.get("rows") or []}
    top=receipt.get("Top3") or []
    # Some formal U receipts intentionally have empty Top3 on WAIT.
    rows=[]
    for x in top:
        code=str(x.get("code") or "")
        src=by_code.get(code,{})
        action=norm_action(x.get("formal_action") or src.get("formal_action"))
        rows.append({
          "code":code,
          "name":x.get("name") or src.get("name"),
          "rank":x.get("rank") or src.get("rank"),
          "score":x.get("score") if x.get("score") is not None else src.get("score"),
          "industry":x.get("industry") or src.get("industry"),
          "action":action,
          "buyable_verified":bool(src.get("buyable_verified")),
          "zone_status":src.get("zone_status"),
          "zone_lower_hkd":src.get("zone_lower_hkd"),
          "zone_upper_hkd":src.get("zone_upper_hkd"),
          "validation":src.get("validation"),
          "macro_position_ceiling_pct":src.get("macro_position_ceiling_pct"),
          "source_row":src,
        })
    return rows


def classify_o(receipt:dict,target_session:str)->dict:
    blockers=[]
    status=str(receipt.get("status") or "")
    if receipt.get("target_session")!=target_session:
        return {"track":"O","state":"STALE","session":receipt.get("target_session"),
                "target_session":target_session,"qualified_buy":0,"candidates":[],"blockers":["STALE_SESSION"]}
    if status.startswith("PASS_FORMAL_O_DECISION_WAIT"):
        if int(receipt.get("official_O_denominator",-1))!=660:
            blockers.append("O_OFFICIAL_DENOMINATOR_NOT_660")
        if int(receipt.get("operational_O_denominator",-1))!=657:
            blockers.append("O_OPERATIONAL_DENOMINATOR_NOT_657")
        if int(receipt.get("current_session_formal_signals",-1))!=0:
            blockers.append("O_CURRENT_SESSION_FORMAL_SIGNAL_NONZERO")
        if int(receipt.get("qualified_buy_in_Top3",-1))!=0:
            blockers.append("O_WAIT_QUALIFIED_BUY_NONZERO")
        if receipt.get("Top3") not in ([],None):
            blockers.append("O_WAIT_TOP3_NOT_EMPTY")
        return {"track":"O","state":"BLOCKED" if blockers else "WAIT","session":target_session,
                "target_session":target_session,"qualified_buy":0,"candidates":[],
                "blockers":sorted(set(blockers))}
    if status!="ACCEPTED_O_FORMAL_TOP3":
        blockers.append("O_FORMAL_ACCEPTANCE_NOT_PASS")
    if int(receipt.get("missing_count",-1))!=0:
        blockers.append("O_MISSING_NOT_ZERO")
    candidates=_o_candidates(receipt)
    claimed=int(receipt.get("qualified_buy_in_Top3",0) or 0)
    buys=[x for x in candidates if x["action"]=="BUY"]
    if claimed!=len(buys):
        blockers.append("O_QUALIFIED_BUY_COUNT_MISMATCH")
    for x in buys:
        if not x["code"] or x["rank"] not in (1,2,3) or x["score"] is None:
            blockers.append("O_BUY_CORE_FIELDS_MISSING")
        if not x["buyable_verified"]:
            blockers.append("O_BUYABILITY_NOT_VERIFIED")
        if not x["industry"]:
            x["industry"]="UNCLASSIFIED"
    if blockers:
        state="BLOCKED"
    elif not buys:
        state="WAIT"
    else:
        state="QUALIFIED_BUY"
    return {"track":"O","state":state,"session":target_session,
            "target_session":target_session,"qualified_buy":len(buys),
            "candidates":candidates,"blockers":sorted(set(blockers))}


def classify_u(receipt:dict,target_session:str)->dict:
    if receipt.get("target_session")!=target_session:
        return {"track":"U","state":"STALE","session":receipt.get("target_session"),
                "target_session":target_session,"qualified_buy":0,"candidates":[],"blockers":["STALE_SESSION"]}
    blockers=[]
    state_value=str(receipt.get("state") or "")
    if not state_value.startswith("PASS_FORMAL_U_DECISION"):
        blockers.append("U_FORMAL_DECISION_NOT_PASS")
    if int(receipt.get("denominator",-1))!=45:
        blockers.append("U_DENOMINATOR_NOT_45")
    if int(receipt.get("formal_valid_rows",-1))<1:
        if state_value=="PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED" and int(receipt.get("qualified_BUY",0) or 0)==0:
            pass
        else:
            blockers.append("U_NO_FORMAL_ROWS")
    candidates=_u_candidates(receipt)
    claimed=int(receipt.get("qualified_BUY",0) or 0)
    buys=[x for x in candidates if x["action"]=="BUY"]
    if claimed!=len(buys):
        blockers.append("U_QUALIFIED_BUY_COUNT_MISMATCH")
    for x in buys:
        if not x["code"] or x["rank"] not in (1,2,3) or x["score"] is None:
            blockers.append("U_BUY_CORE_FIELDS_MISSING")
        if not x["buyable_verified"] or x.get("validation")!="PASS":
            blockers.append("U_BUYABILITY_NOT_VERIFIED")
        if not x["industry"]:
            x["industry"]="UNCLASSIFIED"
        if x.get("zone_status") not in {"APPROVED","VERIFIED","PASS","FORMAL_APPROVED"}:
            blockers.append("U_BUY_ZONE_NOT_APPROVED")
        if x.get("zone_lower_hkd") is None or x.get("zone_upper_hkd") is None:
            blockers.append("U_BUY_ZONE_MISSING")
        if x.get("macro_position_ceiling_pct") is None:
            blockers.append("U_MACRO_CAP_MISSING")
    if blockers:
        state="BLOCKED"
    elif not buys:
        state="WAIT"
    else:
        state="QUALIFIED_BUY"
    return {"track":"U","state":state,"session":target_session,
            "target_session":target_session,"qualified_buy":len(buys),
            "candidates":candidates,"blockers":sorted(set(blockers))}


def build_signal(track:dict,receipt_path:Path,now_iso:str,next_session:str,valid_until:str)->dict:
    account=track["track"]
    passed=track["state"]=="QUALIFIED_BUY"
    top3=[]
    for x in track.get("candidates",[])[:3]:
        top3.append({
          "code":x["code"],"rank":x["rank"],"score":x["score"],
          "industry":x.get("industry"),"action":x["action"],
          "buyable_verified":bool(x.get("buyable_verified")),
        })
    receipt_evidence=evidence(receipt_path)
    signal_id=f"{account}-{track['target_session']}-{sha256_bytes(receipt_path.read_bytes())[:16]}"
    sig={
      **receipt_evidence,
      "id":signal_id,
      "cutoff":now_iso,
      "available_at":now_iso,
      "scope":"forward_simulation",
      "passed":passed,
      "reason":"QUALIFIED_BUY" if passed else track["state"]+"_"+("|".join(track["blockers"]) if track["blockers"] else "NO_BUY"),
      "covered":45 if account=="U" else 657,
      "denominator":45 if account=="U" else 657,
      "data_news_plan_verified":passed,
      "top3":top3,
      "next_session":next_session,
      "valid_until":valid_until,
    }
    if account=="O":
        sig["engine"]="original_native_dsa"
        sig["upstream_commit"]=O_UPSTREAM
    # Macro cap is exposure-only. For U, source rows may carry it.
    if account=="U" and passed:
        caps=[x.get("macro_position_ceiling_pct") for x in track["candidates"] if x["action"]=="BUY"]
        if caps:
            sig["total_cap"]=str(min(caps)/100)
    return {"id":"signal-"+signal_id,"account":account,"at":now_iso,"kind":"SIGNAL","signal":sig}


def build_entry(track:dict,signal_cmd:dict,entry_evidence:dict|None)->tuple[list[dict],list[str]]:
    if track["state"]!="QUALIFIED_BUY":
        return [],[]
    blockers=[]
    if not isinstance(entry_evidence,dict):
        return [],["ENTRY_EVIDENCE_MISSING"]
    # Accept the native collector-v1 shape as well as the legacy flattened shape.
    if entry_evidence.get("status")=="PASS_ENTRY_V1_EVIDENCE" and isinstance(entry_evidence.get("evidence"),dict):
        ev=entry_evidence["evidence"]
        q=ev.get("quote") or {}
        entry_evidence={
          "code":ev.get("code"),"at":q.get("at"),"price":q.get("price"),
          "cny_per_hkd":q.get("cny_per_hkd"),"lot_size":q.get("lot_size"),
          "fee_cny":ev.get("fee_cny"),"source":q.get("source"),"sha256":q.get("sha256"),
          "fx_source":(q.get("fx_evidence") or {}).get("source"),
          "fx_sha256":(q.get("fx_evidence") or {}).get("sha256"),
          "fx_at":(q.get("fx_evidence") or {}).get("at"),
          "session":q.get("session"),"tradable":q.get("tradable"),
          "first_eligible_price_verified":q.get("first_eligible_price_verified"),
          "lot_verified":q.get("lot_verified"),"mode":q.get("mode"),
          "next_session_verified":q.get("next_session_verified"),
          "excluded":ev.get("excluded",{})
        }
    required=("code","at","price","cny_per_hkd","lot_size","fee_cny","source","sha256",
              "fx_source","fx_sha256","session")
    for k in required:
        if entry_evidence.get(k) in (None,""):
            blockers.append("ENTRY_"+k.upper()+"_MISSING")
    if blockers:
        return [],blockers
    code=str(entry_evidence["code"])
    candidates=[x for x in track["candidates"] if x["action"]=="BUY"]
    if code not in {x["code"] for x in candidates}:
        blockers.append("ENTRY_CODE_NOT_QUALIFIED_BUY")
        return [],blockers
    q={
      "verified":True,
      "source":entry_evidence["source"],
      "sha256":entry_evidence["sha256"],
      "at":iso_at(entry_evidence["at"]),
      "price":str(entry_evidence["price"]),
      "cny_per_hkd":str(entry_evidence["cny_per_hkd"]),
      "fx_evidence":{
        "verified":True,"source":entry_evidence["fx_source"],
        "sha256":entry_evidence["fx_sha256"],"at":iso_at(entry_evidence.get("fx_at") or entry_evidence["at"]),
      },
      "tradable":entry_evidence.get("tradable") is True,
      "adjustment":"raw",
      "first_eligible_price_verified":entry_evidence.get("first_eligible_price_verified") is True,
      "mode":entry_evidence.get("mode","tick"),
      "session":entry_evidence["session"],
      "next_session_verified":entry_evidence.get("next_session_verified") is True,
      "lot_size":int(entry_evidence["lot_size"]),
      "lot_verified":entry_evidence.get("lot_verified") is True,
    }
    if not q["tradable"] or not q["first_eligible_price_verified"] or not q["lot_verified"]:
        blockers.append("ENTRY_EXECUTION_EVIDENCE_NOT_VERIFIED")
        return [],blockers
    entry={
      "id":f"entry-{track['track']}-{signal_cmd['signal']['id']}-{code}",
      "account":track["track"],
      "at":q["at"],
      "kind":"ENTRY",
      "signal_id":signal_cmd["signal"]["id"],
      "code":code,
      "quote":q,
      "fee_cny":str(entry_evidence["fee_cny"]),
      "excluded":entry_evidence.get("excluded",{}),
    }
    return [entry],[]


def filter_commands_against_journal(commands:list[dict], journal:dict|None)->tuple[list[dict],list[str]]:
    """Drop exact idempotent commands; reject same-id content drift.

    Production journals persist commands inside hash-linked wrappers
    {parent, command, hash}. Synthetic tests may still supply raw command rows;
    accept both forms but never silently ignore malformed wrapped entries.
    """
    if not isinstance(journal,dict):
        return commands,[]
    existing={}
    for item in (journal.get("commands") or []):
        if not isinstance(item,dict):
            raise ValueError("JOURNAL_COMMAND_ITEM_INVALID")
        if "command" in item:
            raw=item.get("command")
            if not isinstance(raw,dict):
                raise ValueError("JOURNAL_WRAPPED_COMMAND_INVALID")
        else:
            raw=item
        cid=str(raw.get("id") or "")
        if not cid:
            raise ValueError("JOURNAL_COMMAND_ID_MISSING")
        if cid in existing and existing[cid]!=raw:
            raise ValueError("JOURNAL_DUPLICATE_COMMAND_ID_DRIFT:"+cid)
        existing[cid]=raw
    pending=[];noop=[]
    for cmd in commands:
        cid=str(cmd.get("id") or "")
        old=existing.get(cid)
        if old is None:
            pending.append(cmd);continue
        if old!=cmd:
            raise ValueError("COMMAND_ID_CONTENT_DRIFT:"+cid)
        noop.append(cid)
    return pending,noop


def orchestrate(o:dict,u:dict,target_session:str,now_iso:str,next_session:str,
                o_path:Path,u_path:Path,entry:dict|None=None,journal_configured:bool=False,
                cycle:str="preopen")->dict:
    iso_at(now_iso); iso_at(now_iso)
    if cycle not in {"preopen","postclose"}:
        raise ValueError("PRODUCTION_CYCLE_INVALID")
    valid_until=(datetime.fromisoformat(now_iso)+timedelta(days=4)).isoformat()
    tracks={"O":classify_o(o,target_session),"U":classify_u(u,target_session)}
    commands=[]
    entry_blockers={}
    for key,path in (("O",o_path),("U",u_path)):
        signal=build_signal(tracks[key],path,now_iso,next_session,valid_until)
        commands.append(signal)
        ev=(entry or {}).get(key) if isinstance(entry,dict) else None
        if cycle=="postclose" and tracks[key]["state"]=="QUALIFIED_BUY":
            entries,blocks=[],["ENTRY_DEFERRED_TO_PREOPEN"]
        else:
            entries,blocks=build_entry(tracks[key],signal,ev)
        if entries and not journal_configured:
            blocks.append("AUTHORITATIVE_SIMULATION_JOURNAL_UNCONFIGURED")
            entries=[]
        commands.extend(entries)
        entry_blockers[key]=blocks
    q=sum(v["qualified_buy"] for v in tracks.values())
    if any(v["state"]=="BLOCKED" for v in tracks.values()):
        state="BLOCKED"
    elif any(v["state"]=="STALE" for v in tracks.values()):
        state="DEGRADED_STALE"
    elif q and any(entry_blockers.values()):
        state="BUY_ENTRY_BLOCKED"
    elif q:
        state="READY_FOR_SIMULATION_WRITE"
    else:
        state="WAIT_NO_BUY"
    return {
      "schema_version":1,"version":VERSION,"target_session":target_session,
      "generated_at":now_iso,"next_session":next_session,"cycle":cycle,"state":state,
      "tracks":tracks,"qualified_buy_total":q,"entry_blockers":entry_blockers,
      "journal_configured":journal_configured,
      "commands":commands,
      "model_http_requests":0,"broker_orders":0,"real_orders":0,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--o",type=Path,required=True)
    ap.add_argument("--u",type=Path,required=True)
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--now",required=True)
    ap.add_argument("--next-session",required=True)
    ap.add_argument("--entry-evidence",type=Path)
    ap.add_argument("--journal-configured",action="store_true")
    ap.add_argument("--cycle",choices=["preopen","postclose"],default="preopen")
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    entry=json.loads(a.entry_evidence.read_text()) if a.entry_evidence else None
    result=orchestrate(
      json.loads(a.o.read_text()),json.loads(a.u.read_text()),
      a.target_session,a.now,a.next_session,a.o,a.u,entry,a.journal_configured,a.cycle
    )
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({
      "state":result["state"],
      "O":result["tracks"]["O"]["state"],
      "U":result["tracks"]["U"]["state"],
      "qualified_buy_total":result["qualified_buy_total"],
      "journal_configured":result["journal_configured"],
      "command_count":len(result["commands"]),
      "real_orders":0,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
