#!/usr/bin/env python3
"""Qualified BUY gate for normalized O/U formal signals."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def gate(env:dict):
    if env.get("contract")!="DSA_FORMAL_SIGNAL_ENVELOPE_v1":raise ValueError("SIGNAL_CONTRACT_MISMATCH")
    out={"schema_version":1,"contract":"DSA_QUALIFIED_BUY_GATE_v1","tracks":{},"real_orders":0}
    for account in ("O","U"):
        s=env["signals"][account]
        qualified=[x for x in s.get("top3") or [] if x.get("action")=="BUY" and x.get("buyable_verified") is True]
        state="QUALIFIED_BUY" if s.get("passed") and qualified else "WAIT_NO_BUY"
        if bool(qualified)!=bool(s.get("passed")):raise ValueError("SIGNAL_BUY_STATE_CONFLICT:"+account)
        out["tracks"][account]={
          "state":state,"signal_id":s["id"],"qualified":qualified,
          "entry_v1_required":bool(qualified),"simulation_write_required":True,
        }
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--signals",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();o=gate(json.loads(a.signals.read_text()));a.out.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v["state"] for k,v in o["tracks"].items()}))
if __name__=="__main__":main()
