#!/usr/bin/env python3
"""Normalize accepted O/U formal decision receipts into a single simulation SIGNAL contract.

Pure deterministic transform. No network/model/broker access.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime, timedelta, timezone
from pathlib import Path

O_UPSTREAM="089d9d26d68f8b839ea5a74a3784e4402925f8b7"

def sha256_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def action(x):
    v=str(x or "").strip().upper()
    return {"ADD":"BUY","REDUCE":"SELL","WATCH":"HOLD","AVOID":"HOLD","NO":"SELL"}.get(v,v)

def evidence(source_path:Path):
    b=source_path.read_bytes()
    return {"source":str(source_path),"sha256":sha256_bytes(b),"verified":True}

def next_session_from_map(session:str, calendar:dict)->str:
    rows=calendar.get("sessions") or []
    try:i=rows.index(session)
    except ValueError:raise ValueError("TARGET_SESSION_NOT_IN_CALENDAR")
    if i+1>=len(rows):raise ValueError("NEXT_SESSION_MISSING")
    return rows[i+1]

def iso_close(session:str)->str:
    return session+"T16:30:00+08:00"

def iso_valid(next_session:str)->str:
    return next_session+"T16:00:00+08:00"

def build_o(path:Path, obj:dict, calendar:dict):
    if obj.get("status")!="ACCEPTED_O_FORMAL_TOP3" or obj.get("missing_count")!=0:
        raise ValueError("O_FORMAL_NOT_ACCEPTED")
    session=obj["target_session"]; nxt=next_session_from_map(session,calendar)
    top=[]
    for row in obj.get("Top3") or []:
        top.append({
          "code":str(row["code"]).zfill(5),"rank":int(row["rank"]),"score":row.get("sentiment_score"),
          "action":action(row.get("action")),"buyable_verified":action(row.get("action"))=="BUY",
          "industry":row.get("industry") or "UNKNOWN",
        })
    qualified=sum(x["action"]=="BUY" and x["buyable_verified"] for x in top)
    ev=evidence(path)
    sig={
      "id":f"O:{session}:FORMAL","cutoff":iso_close(session),"available_at":iso_close(session),
      "scope":"forward_simulation","passed":qualified>0,
      "reason":"QUALIFIED_BUY_PRESENT" if qualified else "WAIT_NO_QUALIFIED_BUY",
      **ev,
      "covered":int(obj["operational_O_denominator"]),"denominator":int(obj["operational_O_denominator"]),
      "data_news_plan_verified":True,"top3":top,"next_session":nxt,"valid_until":iso_valid(nxt),
      "engine":"original_native_dsa","upstream_commit":O_UPSTREAM,
      "total_cap":None,
    }
    return sig

def build_u(path:Path,obj:dict,calendar:dict):
    if obj.get("track")!="U" or obj.get("state") not in {"PASS_FORMAL_U_DECISION_WAIT_NO_BUY","PASS_FORMAL_U_DECISION_BUY"}:
        raise ValueError("U_FORMAL_NOT_ACCEPTED")
    session=obj["target_session"];nxt=next_session_from_map(session,calendar)
    rows={str(x["code"]).zfill(5):x for x in obj.get("rows") or []}
    raw_top=obj.get("Top3") or []
    # WAIT days intentionally have empty Top3.
    top=[]
    for r in raw_top:
        code=str(r["code"]).zfill(5);src=rows.get(code,{})
        a=action(r.get("formal_action") or src.get("formal_action"))
        top.append({
          "code":code,"rank":int(r.get("rank") or src.get("rank")),"score":r.get("score",src.get("score")),
          "action":a,"buyable_verified":bool(src.get("buyable_verified")) and a=="BUY",
          "industry":src.get("industry") or "UNKNOWN",
          "zone_status":src.get("zone_status"),
          "zone_lower_hkd":src.get("zone_lower_hkd"),"zone_upper_hkd":src.get("zone_upper_hkd"),
        })
    qualified=sum(x["action"]=="BUY" and x["buyable_verified"] for x in top)
    ev=evidence(path)
    macro_caps=[x.get("macro_position_ceiling_pct") for x in rows.values() if x.get("macro_position_ceiling_pct") is not None]
    total_cap=(min(macro_caps)/100) if macro_caps else None
    return {
      "id":f"U:{session}:FORMAL","cutoff":iso_close(session),"available_at":iso_close(session),
      "scope":"forward_simulation","passed":qualified>0,
      "reason":"QUALIFIED_BUY_PRESENT" if qualified else "WAIT_NO_QUALIFIED_BUY",
      **ev,
      "covered":int(obj.get("formal_valid_rows",0)),"denominator":int(obj["denominator"]),
      "data_news_plan_verified":True,"top3":top,"next_session":nxt,"valid_until":iso_valid(nxt),
      "total_cap":total_cap,
    }

def build(o_path:Path,u_path:Path,calendar:dict):
    o=json.loads(o_path.read_text());u=json.loads(u_path.read_text())
    return {"schema_version":1,"contract":"DSA_FORMAL_SIGNAL_ENVELOPE_v1",
            "signals":{"O":build_o(o_path,o,calendar),"U":build_u(u_path,u,calendar)},
            "real_orders":0,"simulation_only":True}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--o",type=Path,required=True);ap.add_argument("--u",type=Path,required=True)
    ap.add_argument("--calendar",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();out=build(a.o,a.u,json.loads(a.calendar.read_text()))
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:{"passed":v["passed"],"reason":v["reason"],"top3":len(v["top3"])} for k,v in out["signals"].items()}))
if __name__=="__main__":main()
