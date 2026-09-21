#!/usr/bin/env python3
"""Resolve authoritative production O/U formal receipts for one target session.

Priority is explicit and fail-closed. Production latest receipts outrank frozen
historical acceptance receipts only when their target_session matches exactly.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p): return json.loads(p.read_text())

def resolve(root:Path,target:str)->dict:
    o_candidates=[
      root/"docs/runtime/O_PRODUCTION_FORMAL_LATEST.json",
      root/"docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json",
    ]
    u_candidates=[
      root/"docs/runtime/U_PRODUCTION_FORMAL_LATEST.json",
      root/"docs/runtime/RUN056_U_FORMAL_RESULT.json",
    ]
    def pick(track,cands):
        checked=[]
        for p in cands:
            if not p.exists():
                checked.append({"path":str(p),"status":"MISSING"});continue
            d=load(p);session=d.get("target_session")
            checked.append({"path":str(p),"status":"MATCH" if session==target else "STALE","session":session})
            if session==target:
                if track=="O":
                    status=str(d.get("status") or "")
                    if status=="ACCEPTED_O_FORMAL_TOP3":
                        ok=int(d.get("missing_count",-1))==0
                    elif status.startswith("PASS_FORMAL_O_DECISION_WAIT"):
                        ok=(
                          int(d.get("official_O_denominator",-1))==660
                          and int(d.get("operational_O_denominator",-1))==657
                          and int(d.get("current_session_formal_signals",-1))==0
                          and int(d.get("qualified_buy_in_Top3",-1))==0
                          and (d.get("Top3") or [])==[]
                        )
                    else:
                        ok=False
                else:
                    ok=str(d.get("state") or "").startswith("PASS_FORMAL_U_DECISION") and int(d.get("denominator",-1))==45
                if not ok:
                    raise ValueError(track+"_MATCHING_RECEIPT_NOT_FORMALLY_USABLE")
                return p,d,checked
        return None,None,checked
    op,od,oc=pick("O",o_candidates);up,ud,uc=pick("U",u_candidates)
    state="READY" if op and up else "MISSING_FORMAL_RECEIPT"
    return {
      "schema_version":1,"target_session":target,"state":state,
      "O":{"path":str(op) if op else None,"receipt":od,"checked":oc},
      "U":{"path":str(up) if up else None,"receipt":ud,"checked":uc},
      "orchestrator_permitted":state=="READY",
      "real_orders":0
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--target-session",required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();r=resolve(a.root,a.target_session)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"state":r["state"],"O":r["O"]["path"],"U":r["U"]["path"]},ensure_ascii=False))
if __name__=="__main__":main()
