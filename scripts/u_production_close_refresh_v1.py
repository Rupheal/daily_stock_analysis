#!/usr/bin/env python3
"""Build a session-scoped U45 close refresh from a frozen native history cache."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path

def _finite(x):
    try:v=float(x)
    except (TypeError,ValueError):return None
    return v if math.isfinite(v) else None

def _code(v):
    s=str(v or "").lower()
    if s.startswith("hk"):s=s[2:]
    return s.zfill(5)

def build(universe:dict,cache:dict,target:str)->dict:
    members=universe.get("members") or []
    if len(members)!=45:
        raise ValueError("U45_UNIVERSE_DENOMINATOR_MISMATCH")
    histories=cache.get("histories") or {}
    if cache.get("target_session") not in (None,target):
        raise ValueError("U45_CACHE_TARGET_MISMATCH")
    facts=[];seen=set()
    for m in members:
        code=_code(m.get("code"))
        if code in seen:raise ValueError("U45_DUPLICATE_CODE")
        seen.add(code)
        raw=histories.get("hk"+code) or histories.get("HK"+code) or histories.get(code)
        rows=[]
        if isinstance(raw,list):rows=raw
        elif isinstance(raw,dict):
            rows=raw.get("rows") or raw.get("history") or raw.get("data") or []
        normalized=[]
        for r in rows:
            if isinstance(r,dict):
                d=str(r.get("date") or r.get("time_key") or "")[:10]
                normalized.append((d,r))
            elif isinstance(r,(list,tuple)) and len(r)>=6:
                normalized.append((str(r[0])[:10],{"open":r[1],"high":r[2],"low":r[3],"close":r[4],"volume":r[5]}))
        matches=[r for d,r in normalized if d==target]
        row=matches[-1] if matches else None
        vals={k:_finite((row or {}).get(k)) for k in ("open","high","low","close","volume")}
        valid=bool(row and all(vals[k] is not None for k in vals) and vals["close"]>0 and vals["volume"]>=0)
        facts.append({
          "code":code,"official_name":m.get("official_name"),"english_name":m.get("english_name"),
          "target_session":target,"current_valid_bar":valid,
          "latest_date":target if valid else (normalized[-1][0] if normalized else None),
          **(vals if valid else {"open":None,"high":None,"low":None,"close":None,"volume":None}),
        })
    ready=sum(x["current_valid_bar"] for x in facts)
    return {
      "schema_version":1,"run_id":"DSA-U-CLOSE-"+target.replace("-",""),
      "target_session":target,"denominator":45,"current_valid_count":ready,
      "status":"PASS_CURRENT_SESSION_FACT_REFRESH" if ready==45 else "PARTIAL_CURRENT_SESSION_FACT_REFRESH",
      "facts":facts,
      "boundary":"Frozen native-cache close facts only; not a strategy signal or independent execution quote.",
      "model_http_requests":0,"real_orders":0
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--universe",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--target-session",required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    r=build(json.loads(a.universe.read_text()),json.loads(a.cache.read_text()),a.target_session)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"target":r["target_session"],"current_valid":r["current_valid_count"],"status":r["status"]}))
if __name__=="__main__":main()
