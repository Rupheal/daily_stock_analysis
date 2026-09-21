#!/usr/bin/env python3
"""Cost/value routing for O daily production.

This module never changes O strategy semantics. It decides whether paid
full-pool inference is permitted at all. Selective mode remains fail-closed until
a separately accepted calibration manifest exists.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

MODES={"R0_ONLY","CALIBRATION_FULL","SELECTIVE"}

def decide(mode:str, operational:int, calibration:dict|None=None)->dict:
    if mode not in MODES: raise ValueError("O_COST_ROUTE_MODE_INVALID")
    if operational<0: raise ValueError("O_OPERATIONAL_DENOMINATOR_INVALID")
    if mode=="R0_ONLY":
        return {"mode":mode,"paid_model_permitted":False,"paid_member_limit":0,
                "formal_full_universe_claim_permitted":False,
                "reason":"DEFAULT_R0_FULL_UNIVERSE_REFRESH"}
    if mode=="CALIBRATION_FULL":
        return {"mode":mode,"paid_model_permitted":True,"paid_member_limit":operational,
                "per_member_cap_cny":"0.10","session_hard_ceiling_cny":"65.70",
                "formal_full_universe_claim_permitted":True,
                "reason":"EXPLICIT_FULL_SCAN_CALIBRATION"}
    c=calibration or {}
    if c.get("status")!="ACCEPTED_SELECTIVE_ROUTER":
        return {"mode":mode,"paid_model_permitted":False,"paid_member_limit":0,
                "formal_full_universe_claim_permitted":False,
                "reason":"SELECTIVE_ROUTER_NOT_CALIBRATED"}
    limit=int(c.get("paid_member_limit",0))
    if not (1<=limit<=operational): raise ValueError("SELECTIVE_PAID_MEMBER_LIMIT_INVALID")
    return {"mode":mode,"paid_model_permitted":True,"paid_member_limit":limit,
            "formal_full_universe_claim_permitted":False,
            "reason":"ACCEPTED_SELECTIVE_ROUTER",
            "calibration_id":c.get("calibration_id")}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--mode",choices=sorted(MODES),default="R0_ONLY")
    ap.add_argument("--operational",type=int,required=True);ap.add_argument("--calibration",type=Path)
    ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    c=json.loads(a.calibration.read_text()) if a.calibration and a.calibration.exists() else None
    r=decide(a.mode,a.operational,c);a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,indent=2)+"\n");print(json.dumps(r))
if __name__=="__main__":main()
