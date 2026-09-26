#!/usr/bin/env python3
"""DSA Production Session Driver v1.

Deterministically resolves Hong Kong production cycle boundaries:
- PREOPEN/ENTRY: current decision session, previous completed price session.
- POSTCLOSE: 16:30 HKT, consume the just-completed XHKG session.
- weekends/holidays never fabricate a new session.

It does not call models, brokers, or data providers. It only decides whether
current O/U formal receipts are fresh enough to enter the production orchestrator.
"""
from __future__ import annotations
import argparse,json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import exchange_calendars as xcals

from o_target_session_contract import resolve_target_session
from dsa_production_orchestrator_v1 import classify_o, classify_u, build_signal

HK=ZoneInfo("Asia/Hong_Kong")
CAL=xcals.get_calendar("XHKG")
VERSION="DSA_PRODUCTION_SESSION_DRIVER_v1"


def next_session_after(session:str)->str:
    s=CAL.date_to_session(session,direction="none")
    return CAL.next_session(s).date().isoformat()


def classify_window(at:datetime)->str:
    h=at.astimezone(HK)
    # Clock windows cannot authorize work on a non-session date.
    if not CAL.is_session(h.date().isoformat()):
        return "OFF_WINDOW"
    hm=h.hour*60+h.minute
    if 8*60+45 <= hm <= 9*60+20:
        return "PREOPEN"
    # Owner-approved Entry-v1: 09:30 inclusive, 10:00 exclusive.
    if 9*60+30 <= hm < 10*60:
        return "ENTRY"
    if 16*60+15 <= hm <= 17*60:
        return "POSTCLOSE"
    return "OFF_WINDOW"


def drive(at_iso:str,o:dict,u:dict)->dict:
    at=datetime.fromisoformat(at_iso.replace("Z","+00:00"))
    if at.tzinfo is None: raise ValueError("NAIVE_TIMESTAMP")
    hkt=at.astimezone(HK)
    window=classify_window(at)
    if window in ("PREOPEN","ENTRY"):
        target=hkt.date().isoformat()
        market=CAL.previous_session(target).date().isoformat()
        nxt=next_session_after(target)
    else:
        target=resolve_target_session(at).target_session.isoformat()
        market=target
        nxt=next_session_after(target)
    o_session=o.get("target_session")
    u_session=u.get("target_session")
    o_fresh=(o_session==target and o.get("status")=="ACCEPTED_O_FORMAL_TOP3" and int(o.get("missing_count",-1))==0)
    u_state=str(u.get("state") or "")
    u_fresh=(u_session==target and u_state.startswith("PASS_FORMAL_U_DECISION"))
    morning_errors={"O":[],"U":[]}
    if window in ("PREOPEN","ENTRY"):
        # This is routing eligibility, not AM acceptance or entry permission.
        # Reuse the consumer's timing validator; the accepted Entry-v1 binding
        # still verifies AM acceptance, freeze, prices and orders downstream.
        with tempfile.TemporaryDirectory() as td:
            for account,receipt,classifier in (("O",o,classify_o),("U",u,classify_u)):
                try:
                    if receipt.get("target_session")!=target:
                        raise ValueError("CURRENT_MORNING_RECEIPT_REQUIRED")
                    if receipt.get("market_data_session")!=market:
                        raise ValueError("PREVIOUS_PRICE_SESSION_REQUIRED")
                    track=classifier(receipt,target)
                    if track["state"] not in ("WAIT","QUALIFIED_BUY"):
                        raise ValueError("MORNING_FORMAL_RESULT_NOT_USABLE")
                    path=Path(td)/f"{account}.json"
                    path.write_text(json.dumps(receipt))
                    signal=build_signal(track,path,at_iso,nxt,receipt=receipt)["signal"]
                    for field in ("cutoff","available_at"):
                        ts=datetime.fromisoformat(signal[field]).astimezone(HK)
                        if ts.date().isoformat()!=target or (ts.hour,ts.minute,ts.second,ts.microsecond)>(9,25,0,0):
                            raise ValueError("CURRENT_PRE_FREEZE_TIMING_REQUIRED")
                except (ValueError,KeyError,TypeError,AttributeError) as exc:
                    morning_errors[account].append(str(exc))
        o_fresh=o_fresh and not morning_errors["O"]
        u_fresh=u_fresh and not morning_errors["U"]
    if window=="OFF_WINDOW":
        state="OFF_WINDOW_NO_ACTION"
    elif o_fresh and u_fresh:
        state="READY_FOR_ORCHESTRATOR"
    else:
        state="NEEDS_FORMAL_REFRESH"
    return {
      "schema_version":1,"version":VERSION,"evaluation_time_hkt":hkt.isoformat(),
      "window":window,"target_session":target,"decision_session":target,
      "market_data_session":market,"next_session":nxt,"state":state,
      "morning_blockers":morning_errors,"entry_policy_acceptance_verified":False,
      "tracks":{
        "O":{"receipt_session":o_session,"fresh":o_fresh,
             "required_action":"NONE" if o_fresh else "REFRESH_O_FORMAL"},
        "U":{"receipt_session":u_session,"fresh":u_fresh,
             "required_action":"NONE" if u_fresh else "REFRESH_U_FORMAL"},
      },
      "production_orchestrator_permitted":state=="READY_FOR_ORCHESTRATOR",
      "model_http_requests":0,"broker_orders":0,"real_orders":0,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--at",required=True)
    ap.add_argument("--o",type=Path,required=True)
    ap.add_argument("--u",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    r=drive(a.at,json.loads(a.o.read_text()),json.loads(a.u.read_text()))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(r,ensure_ascii=False))

if __name__=="__main__":main()
