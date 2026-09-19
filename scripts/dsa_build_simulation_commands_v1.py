#!/usr/bin/env python3
"""Build idempotent simulation SIGNAL commands from formal envelope.

ENTRY commands are deliberately absent unless a separately verified Entry-v1 receipt exists.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path

def commands(env:dict,entry:dict|None=None):
    out=[]
    for account in ("O","U"):
        s=env["signals"][account]
        out.append({"id":f"SIGNAL:{s['id']}","account":account,"at":s["available_at"],"kind":"SIGNAL","signal":s})
    if entry:
        for row in entry.get("entries") or []:
            if row.get("status")!="PASS_ENTRY_V1":continue
            out.append({
              "id":row["command_id"],"account":row["account"],"at":row["at"],"kind":"ENTRY",
              "signal_id":row["signal_id"],"code":row["code"],"quote":row["quote"],
              "fee_cny":row["fee_cny"],"excluded":row.get("excluded") or {},
            })
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--signals",type=Path,required=True);ap.add_argument("--entry",type=Path);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();env=json.loads(a.signals.read_text());entry=json.loads(a.entry.read_text()) if a.entry else None
    out=commands(env,entry);a.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"commands":len(out),"entries":sum(x["kind"]=="ENTRY" for x in out)}))
if __name__=="__main__":main()
