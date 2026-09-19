#!/usr/bin/env python3
"""Entry-v1 execution evidence collector contract.

This module intentionally separates *collection* from *validation*. Provider
adapters may fill quote/lot/fx/fee fields, but a simulation ENTRY is emitted
only when every required field is verified and source-bound.

No broker order API is imported or called.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime
from pathlib import Path

VERSION="DSA_ENTRY_EVIDENCE_COLLECTOR_v1"


def _sha(obj)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


def _aware(value):
    try:d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception:return False
    return d.tzinfo is not None


def build(code:str, quote:dict|None, lot:dict|None, fx:dict|None, fee:dict|None, industry:dict|None)->dict:
    blockers=[]
    if not quote or quote.get("verified") is not True:
        blockers.append("QUOTE_UNVERIFIED")
    else:
        if not _aware(quote.get("at")):blockers.append("QUOTE_TIMESTAMP_INVALID")
        if not quote.get("source"):blockers.append("QUOTE_SOURCE_MISSING")
        if not isinstance(quote.get("price"),(int,float,str)):blockers.append("QUOTE_PRICE_MISSING")
        try:
            if float(quote.get("price"))<=0:blockers.append("QUOTE_PRICE_INVALID")
        except Exception:blockers.append("QUOTE_PRICE_INVALID")
        if quote.get("tradable") is not True:blockers.append("QUOTE_NOT_TRADABLE")
        if quote.get("adjustment")!="raw":blockers.append("QUOTE_NOT_RAW")
        if quote.get("first_eligible_price_verified") is not True:blockers.append("FIRST_ELIGIBLE_PRICE_UNVERIFIED")

    if not lot or lot.get("verified") is not True:
        blockers.append("BOARD_LOT_UNVERIFIED")
    else:
        try:
            if int(lot.get("lot_size"))<=0:blockers.append("BOARD_LOT_INVALID")
        except Exception:blockers.append("BOARD_LOT_INVALID")
        if not lot.get("source"):blockers.append("BOARD_LOT_SOURCE_MISSING")

    if not fx or fx.get("verified") is not True:
        blockers.append("FX_UNVERIFIED")
    else:
        if not _aware(fx.get("at")):blockers.append("FX_TIMESTAMP_INVALID")
        try:
            if float(fx.get("cny_per_hkd"))<=0:blockers.append("FX_RATE_INVALID")
        except Exception:blockers.append("FX_RATE_INVALID")
        if not fx.get("source"):blockers.append("FX_SOURCE_MISSING")

    if not fee or fee.get("verified") is not True:
        blockers.append("FEE_POLICY_UNVERIFIED")
    else:
        try:
            fee_cny=float(fee.get("fee_cny"))
            if fee_cny<0:blockers.append("FEE_INVALID")
        except Exception:blockers.append("FEE_INVALID")
        if not fee.get("source"):blockers.append("FEE_SOURCE_MISSING")

    if not industry or industry.get("verified") is not True or not industry.get("industry"):
        blockers.append("INDUSTRY_UNVERIFIED")

    passed=not blockers
    evidence=None
    if passed:
        q={
          "verified":True,"source":quote["source"],"sha256":quote.get("sha256") or _sha(quote),
          "at":quote["at"],"price":str(quote["price"]),
          "cny_per_hkd":str(fx["cny_per_hkd"]),
          "fx_evidence":{
            "verified":True,"source":fx["source"],"sha256":fx.get("sha256") or _sha(fx),"at":fx["at"]
          },
          "tradable":True,"adjustment":"raw","first_eligible_price_verified":True,
          "mode":quote.get("mode","tick"),"lot_size":int(lot["lot_size"]),"lot_verified":True,
        }
        if q["mode"]=="daily_open":
            q["next_session_verified"]=quote.get("next_session_verified") is True
            if not q["next_session_verified"]:
                blockers.append("NEXT_SESSION_UNVERIFIED");passed=False
        if passed:
            evidence={
              "code":code,"industry":industry["industry"],"fee_cny":str(fee["fee_cny"]),
              "quote":q,"excluded":{},"evidence_version":VERSION,
              "source_hashes":{
                "quote":q["sha256"],"lot":lot.get("sha256") or _sha(lot),
                "fx":q["fx_evidence"]["sha256"],"fee":fee.get("sha256") or _sha(fee),
                "industry":industry.get("sha256") or _sha(industry),
              }
            }
    return {
      "schema_version":1,"version":VERSION,"code":code,
      "status":"PASS_ENTRY_V1_EVIDENCE" if passed else "BLOCKED_ENTRY_V1_EVIDENCE",
      "blockers":blockers,"evidence":evidence,
      "real_orders":0,"broker_order_calls":0,
    }


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--code",required=True)
    for n in ("quote","lot","fx","fee","industry"):ap.add_argument("--"+n,type=Path)
    ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    load=lambda p: json.loads(p.read_text()) if p and p.exists() else None
    r=build(a.code,load(a.quote),load(a.lot),load(a.fx),load(a.fee),load(a.industry))
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":r["status"],"blockers":r["blockers"],"real_orders":0}))
if __name__=="__main__":main()
