#!/usr/bin/env python3
"""Validate a default-branch initiated Daily Formal trigger."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import exchange_calendars as xcals

def validate(t:dict)->dict:
    if t.get("schema_version")!=1 or t.get("arm_token")!="DSA_DAILY_FORMAL_v1":
        raise ValueError("DAILY_FORMAL_TRIGGER_SCHEMA_OR_TOKEN")
    if t.get("armed") is not True:
        raise ValueError("DAILY_FORMAL_NOT_ARMED")
    target=str(t.get("target_session") or "")
    cal=xcals.get_calendar("XHKG")
    s=cal.date_to_session(target,direction="none")
    if s.date().isoformat()!=target:
        raise ValueError("TARGET_NOT_XHKG_SESSION")
    return {"schema_version":1,"target_session":target,"nonce":str(t.get("nonce") or ""),
            "O_enabled":bool(t.get("O_enabled",True)),"U_enabled":bool(t.get("U_enabled",True)),
            "real_orders":0}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--trigger",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();r=validate(json.loads(a.trigger.read_text()))
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2)+"\n")
    print(json.dumps(r))
if __name__=="__main__":main()
