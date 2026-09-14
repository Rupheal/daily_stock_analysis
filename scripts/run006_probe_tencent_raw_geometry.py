"""Diagnose the 7 frozen missing/stale-history isolates using Tencent raw and qfq history.

Diagnostic only. Does not rewrite frozen historical inputs or predictions.
"""
from __future__ import annotations
import argparse, hashlib, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FIELDS=("open","high","low","close","volume")
TARGET="2026-09-11"


def canonical(code: str) -> str:
    return "HK"+str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def valid_geometry(row: dict) -> bool:
    try: v={k:Decimal(str(row[k])) for k in FIELDS}
    except Exception: return False
    return all(x.is_finite() for x in v.values()) and 0 < v["low"] <= min(v["open"],v["close"]) <= max(v["open"],v["close"]) <= v["high"] and v["volume"] >= 0


def parse_rows(rows):
    out=[]
    for r in rows or []:
        if not isinstance(r,list) or len(r)<6: continue
        out.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    return out


def fetch_tencent(code: str, adjusted: bool):
    code=canonical(code)
    if adjusted:
        url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":code.lower()+",day,,,180,qfq"})
    else:
        url="https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"+urlencode({"param":code.lower()+",day,,,180"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=25) as resp:
        raw=resp.read(2_000_000)
    payload=json.loads(raw); item=(payload.get("data") or {}).get(code.lower()) or {}
    rows=parse_rows((item.get("qfqday") if adjusted else None) or item.get("day") or [])
    return hashlib.sha256(raw).hexdigest(),rows


def main():
    p=argparse.ArgumentParser(); p.add_argument("--integrity",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    src=json.loads(a.integrity.read_text())
    assert src["track"]=="O" and src["denominator"]==660 and src["isolated"]==253
    targets=[r for r in src["coverage"] if "missing_latest_session_or_21_bar_history" in r.get("reason","")]
    if len(targets)!=7: raise ValueError(f"missing_history_denominator_changed:{len(targets)}")
    out=[]; lock=Lock()
    def one(r):
        code=canonical(r["code"]); rec={"code":code,"frozen_reason":r.get("reason")}
        try:
            rsha,raw=fetch_tencent(code,False); qsha,qfq=fetch_tencent(code,True)
            raw=[x for x in raw if x["date"]<=TARGET]; qfq=[x for x in qfq if x["date"]<=TARGET]
            nonzero=[x for x in raw if Decimal(str(x["volume"]))>0]
            rec.update(raw_sha256=rsha,qfq_sha256=qsha,raw_count=len(raw),qfq_count=len(qfq),raw_first=(raw[0]["date"] if raw else None),raw_latest=(raw[-1]["date"] if raw else None),qfq_first=(qfq[0]["date"] if qfq else None),qfq_latest=(qfq[-1]["date"] if qfq else None),latest_nonzero_date=(nonzero[-1]["date"] if nonzero else None),latest_raw_volume=(str(raw[-1]["volume"]) if raw else None))
            recent=qfq[-21:]
            if not qfq or len(qfq)<21:
                rec["classification"]="TRUE_INSUFFICIENT_HISTORY_OR_NEW_LISTING"
            elif qfq[-1]["date"]<TARGET:
                rec["classification"]="STALE_OR_SUSPENDED_BEFORE_TARGET"
            elif raw and Decimal(str(raw[-1]["volume"]))==0 and (not nonzero or nonzero[-1]["date"]<TARGET):
                rec["classification"]="NO_TRADE_OR_SUSPENDED_ON_TARGET"
            elif any(not valid_geometry(x) for x in recent):
                rec["classification"]="TENCENT_HISTORY_GEOMETRY_INVALID"
            else:
                rec["classification"]="RECOVERABLE_YAHOO_HISTORY_GAP"
                rec["recent21_sha256"]=hashlib.sha256(json.dumps(recent,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        except Exception as exc:
            rec.update(classification="TENCENT_STATUS_FETCH_OR_PARSE_FAILURE",error=type(exc).__name__+":"+str(exc)[:180])
        with lock: out.append(rec)
    with ThreadPoolExecutor(max_workers=7) as pool: list(pool.map(one,targets))
    out.sort(key=lambda x:x["code"]); counts={}
    for r in out: counts[r["classification"]]=counts.get(r["classification"],0)+1
    report={"schema_version":7,"run_id":"TRI-DSA-DAT-20260914-006-MISSING-HISTORY-R7","generated_at":datetime.now(timezone.utc).isoformat(),"source_integrity_sha256":hashlib.sha256(a.integrity.read_bytes()).hexdigest(),"original_recovery_denominator":253,"missing_history_denominator":7,"target":TARGET,"classification_counts":counts,"rows":out,"model_http_requests":0,"paid_data_used":False,"historical_inputs_rewritten":False,"frozen_predictions_rewritten":False}
    if len(out)!=7 or sum(counts.values())!=7: raise ValueError("diagnostic_accounting_failure")
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)); print("RUN006_MISSING_HISTORY_R7",json.dumps(counts,ensure_ascii=False),flush=True); print("RUN006_MISSING_ROWS",json.dumps(out,ensure_ascii=False),flush=True)

if __name__=="__main__": main()
