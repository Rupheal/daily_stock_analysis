#!/usr/bin/env python3
"""Build sanitized production-status block for Dashboard v0.19 feed."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def build(runtime:dict|None,journal:dict|None)->dict:
    if runtime is None:
        return {"status":"NOT_RUN","simulation_only":True,"real_orders":0}
    state=runtime.get("state")
    out={
      "status":state or "UNKNOWN",
      "simulation_only":True,
      "real_orders":int(runtime.get("real_orders",0) or 0),
      "simulation_write_performed":bool(runtime.get("simulation_write_performed",False)),
      "target_session":((runtime.get("route") or {}).get("target_session")),
      "next_session":((runtime.get("route") or {}).get("next_session")),
      "O_state":(((runtime.get("orchestrator") or {}).get("tracks") or {}).get("O") or {}).get("state"),
      "U_state":(((runtime.get("orchestrator") or {}).get("tracks") or {}).get("U") or {}).get("state"),
      "entry_state":(((runtime.get("orchestrator") or {}).get("entry") or {}).get("state")),
      "journal_state":(journal or {}).get("state"),
      "journal_command_count":(journal or {}).get("command_count"),
    }
    if out["real_orders"]!=0: raise ValueError("REAL_ORDER_BOUNDARY_BREACH")
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--runtime",type=Path);ap.add_argument("--journal",type=Path)
    ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    load=lambda p:json.loads(p.read_text()) if p and p.exists() else None
    r=build(load(a.runtime),load(a.journal));a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n");print(json.dumps(r))
if __name__=="__main__":main()
