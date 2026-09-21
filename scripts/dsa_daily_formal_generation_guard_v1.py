#!/usr/bin/env python3
"""Distinguish a generated formal decision from a fallback WAIT receipt.

A fallback WAIT is legitimate Authority for "do nothing now", but it is NOT
proof that the O/U ranking engine actually ran for the target session.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

O_GENERATED="ACCEPTED_O_FORMAL_TOP3"
O_FALLBACK_PREFIX="PASS_FORMAL_O_DECISION_WAIT"
U_PREFIX="PASS_FORMAL_U_DECISION"

def assess_o(receipt:dict,target:str)->dict:
    if receipt.get("target_session")!=target:
        return {"track":"O","state":"STALE","generation_complete":False,"entry_evaluation_permitted":False,"reason":"STALE_SESSION"}
    status=str(receipt.get("status") or "")
    if status==O_GENERATED:
        missing=int(receipt.get("missing_count",-1))
        ranked=int(receipt.get("ranking_eligible_count",-1))
        complete=missing==0 and ranked>=1
        return {"track":"O","state":"GENERATED" if complete else "INVALID_GENERATED_RECEIPT",
                "generation_complete":complete,"entry_evaluation_permitted":complete,
                "reason":"O_FORMAL_RANKING_GENERATED" if complete else "O_GENERATED_RECEIPT_INCOMPLETE"}
    if status.startswith(O_FALLBACK_PREFIX):
        return {"track":"O","state":"MISSING_GENERATION","generation_complete":False,
                "entry_evaluation_permitted":False,"reason":"O_CURRENT_SESSION_RANKING_NOT_GENERATED"}
    return {"track":"O","state":"INVALID_FORMAL_STATE","generation_complete":False,
            "entry_evaluation_permitted":False,"reason":"O_FORMAL_STATE_UNRECOGNIZED"}

def assess_u(receipt:dict,target:str)->dict:
    if receipt.get("target_session")!=target:
        return {"track":"U","state":"STALE","generation_complete":False,"entry_evaluation_permitted":False,"reason":"STALE_SESSION"}
    state=str(receipt.get("state") or "")
    if not state.startswith(U_PREFIX):
        return {"track":"U","state":"INVALID_FORMAL_STATE","generation_complete":False,
                "entry_evaluation_permitted":False,"reason":"U_FORMAL_STATE_UNRECOGNIZED"}
    rows=int(receipt.get("formal_valid_rows",-1))
    skipped=receipt.get("provider_skipped") is True
    if skipped or rows<1:
        return {"track":"U","state":"MISSING_GENERATION","generation_complete":False,
                "entry_evaluation_permitted":False,
                "reason":"U_FORMAL_PROVIDER_NOT_RUN_OR_NO_VALID_ROWS",
                "prerequisite_blockers":receipt.get("prerequisite_blockers") or []}
    return {"track":"U","state":"GENERATED","generation_complete":True,
            "entry_evaluation_permitted":True,"reason":"U_FORMAL_DECISION_GENERATED",
            "formal_valid_rows":rows,"qualified_BUY":int(receipt.get("qualified_BUY",0) or 0)}

def assess_pair(o:dict,u:dict,target:str)->dict:
    O=assess_o(o,target); U=assess_u(u,target)
    complete=O["generation_complete"] and U["generation_complete"]
    return {
      "schema_version":1,"target_session":target,"O":O,"U":U,
      "state":"READY_FOR_ENTRY_EVALUATION" if complete else "WAIT_DAILY_FORMAL_GENERATION",
      "generation_complete":complete,
      "entry_evaluation_permitted":complete,
      "real_orders":0,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--o",type=Path,required=True);ap.add_argument("--u",type=Path,required=True)
    ap.add_argument("--target-session",required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    r=assess_pair(json.loads(a.o.read_text()),json.loads(a.u.read_text()),a.target_session)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"state":r["state"],"O":r["O"]["state"],"U":r["U"]["state"]}))
if __name__=="__main__":main()
