"""Diagnose 132 frozen cross-source disagreements using Yahoo raw vs Tencent raw.

Diagnostic only. Does not rewrite frozen historical inputs or predictions.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yfinance as yf

FIELDS=("open","high","low","close","volume")
PRICE_FIELDS=("open","high","low","close")
TARGET="2026-09-11"


def canonical(code: str) -> str:
    return "HK"+str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def yahoo_symbol(code: str) -> str:
    n=canonical(code)[2:].lstrip("0") or "0"
    return n.zfill(4)+".HK"


def valid_geometry(row: dict) -> bool:
    try:
        v={k:Decimal(str(row[k])) for k in FIELDS}
    except Exception:
        return False
    return all(x.is_finite() for x in v.values()) and 0 < v["low"] <= min(v["open"],v["close"]) <= max(v["open"],v["close"]) <= v["high"] and v["volume"] >= 0


def fetch_tencent_raw(code: str):
    code=canonical(code)
    url="https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"+urlencode({"param":code.lower()+",day,,,180"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=25) as resp:
        raw=resp.read(2_000_000)
    payload=json.loads(raw)
    item=(payload.get("data") or {}).get(code.lower()) or {}
    rows=item.get("day") or []
    parsed=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<6: continue
        parsed.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    if not parsed: raise ValueError("tencent_raw_rows_missing")
    return hashlib.sha256(raw).hexdigest(), parsed


def fetch_yahoo_raw(code: str):
    sym=yahoo_symbol(code)
    frame=yf.Ticker(sym).history(start="2026-07-01",end="2026-09-12",auto_adjust=False,actions=True,timeout=20)
    if frame is None or frame.empty: raise ValueError("yahoo_raw_rows_missing")
    rows=[]
    for idx,row in frame.iterrows():
        vals={k:row.get(k.title()) for k in PRICE_FIELDS}
        volume=row.get("Volume")
        if any(v is None or (isinstance(v,float) and math.isnan(v)) for v in vals.values()) or volume is None:
            continue
        rows.append({"date":str(idx)[:10],"open":float(vals["open"]),"high":float(vals["high"]),"low":float(vals["low"]),"close":float(vals["close"]),"volume":float(volume)})
    if not rows: raise ValueError("yahoo_raw_rows_empty_after_parse")
    return sym,rows


def compare_raw(yrows,trows):
    y={r["date"]:r for r in yrows if r["date"]<=TARGET}
    t={r["date"]:r for r in trows if r["date"]<=TARGET}
    dates=sorted(set(y)&set(t))[-21:]
    if len(dates)<21: return "RAW_INSUFFICIENT_OVERLAP",{"overlap":len(dates)}
    if dates[-1]!=TARGET: return "RAW_STALE_LATEST",{"overlap":len(dates),"latest":dates[-1]}
    if any(not valid_geometry(y[d]) for d in dates): return "YAHOO_RAW_GEOMETRY_INVALID",{"overlap":len(dates)}
    if any(not valid_geometry(t[d]) for d in dates): return "TENCENT_RAW_GEOMETRY_INVALID",{"overlap":len(dates)}
    tight=True; loose=True; max_abs=0.0; max_rel=0.0; samples=[]
    for d in dates:
        for f in PRICE_FIELDS:
            a=float(y[d][f]); b=float(t[d][f]); diff=abs(a-b); scale=max(abs(a),abs(b),1e-9); rel=diff/scale
            max_abs=max(max_abs,diff); max_rel=max(max_rel,rel)
            if diff>max(0.01,0.001*scale): tight=False
            if diff>max(0.02,0.002*scale): loose=False
            if len(samples)<8 and diff>0: samples.append({"date":d,"field":f,"yahoo":a,"tencent":b,"abs_diff":diff,"rel_diff":rel})
    if tight: cls="RAW_PRICE_AGREEMENT_TIGHT"
    elif loose: cls="RAW_PRICE_AGREEMENT_LOOSE"
    else: cls="RAW_PRICE_CONFLICT"
    return cls,{"overlap":len(dates),"max_abs_price_diff":max_abs,"max_rel_price_diff":max_rel,"samples":samples}


def main():
    p=argparse.ArgumentParser(); p.add_argument("--integrity",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    src=json.loads(a.integrity.read_text())
    assert src["track"]=="O" and src["denominator"]==660 and src["isolated"]==253
    targets=[r for r in src["coverage"] if r.get("reason")=="independent_daily_disagreement"]
    if len(targets)!=132: raise ValueError("disagreement_denominator_changed")
    out=[]; lock=Lock()
    def one(r):
        code=canonical(r["code"]); rec={"code":code,"frozen_reason":r.get("reason")}
        try:
            tsha,trows=fetch_tencent_raw(code); ysym,yrows=fetch_yahoo_raw(code)
            cls,diag=compare_raw(yrows,trows)
            rec.update(classification=cls,tencent_response_sha256=tsha,yahoo_symbol=ysym,**diag)
            if cls in ("RAW_PRICE_AGREEMENT_TIGHT","RAW_PRICE_AGREEMENT_LOOSE"):
                rec["recovery_interpretation"]="ADJUSTMENT_OR_ROUNDING_DISAGREEMENT_LIKELY"
            elif cls=="RAW_PRICE_CONFLICT":
                rec["recovery_interpretation"]="TRUE_RAW_SOURCE_CONFLICT_RETAIN_ISOLATED"
        except Exception as exc:
            rec.update(classification="RAW_FETCH_OR_PARSE_FAILURE",error=type(exc).__name__+":"+str(exc)[:180])
        with lock: out.append(rec)
    with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(one,targets))
    out.sort(key=lambda x:x["code"]); counts={}
    for r in out: counts[r["classification"]]=counts.get(r["classification"],0)+1
    report={"schema_version":6,"run_id":"TRI-DSA-DAT-20260914-006-DISAGREEMENT-RAW-R6","generated_at":datetime.now(timezone.utc).isoformat(),"source_integrity_sha256":hashlib.sha256(a.integrity.read_bytes()).hexdigest(),"original_recovery_denominator":253,"disagreement_denominator":132,"target":TARGET,"classification_counts":counts,"rows":out,"model_http_requests":0,"paid_data_used":False,"historical_inputs_rewritten":False,"frozen_predictions_rewritten":False}
    if len(out)!=132 or sum(counts.values())!=132: raise ValueError("diagnostic_accounting_failure")
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)); print("RUN006_RAW_DISAGREEMENT_R6",json.dumps(counts,ensure_ascii=False),flush=True)

if __name__=="__main__": main()
