"""Validate Tencent qfq fallback for the 114 frozen Yahoo geometry isolates.

Diagnostic only: never rewrites frozen historical inputs or predictions.
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
    try:
        v={k:Decimal(str(row[k])) for k in FIELDS}
    except Exception:
        return False
    return all(x.is_finite() for x in v.values()) and 0 < v["low"] <= min(v["open"],v["close"]) <= max(v["open"],v["close"]) <= v["high"] and v["volume"] >= 0


def fetch_qfq(code: str):
    code=canonical(code)
    url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":code.lower()+",day,,,180,qfq"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=25) as resp:
        raw=resp.read(2_000_000)
    payload=json.loads(raw)
    item=(payload.get("data") or {}).get(code.lower()) or {}
    rows=item.get("qfqday") or item.get("day") or []
    parsed=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<6: continue
        parsed.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    if not parsed: raise ValueError("qfq_rows_missing")
    return hashlib.sha256(raw).hexdigest(), parsed


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--integrity",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    src=json.loads(a.integrity.read_text())
    assert src["track"]=="O" and src["denominator"]==660 and src["isolated"]==253
    targets=[r for r in src["coverage"] if "invalid_daily_geometry" in r.get("reason","")]
    if len(targets)!=114: raise ValueError("geometry_denominator_changed")
    out=[]; lock=Lock()
    def one(r):
        code=canonical(r["code"]); rec={"code":code,"frozen_reason":r.get("reason")}
        try:
            sha,rows=fetch_qfq(code)
            rows=[x for x in rows if x["date"]<=TARGET]
            recent=rows[-21:]
            rec.update(response_sha256=sha,session_count_to_target=len(rows),latest_date=(rows[-1]["date"] if rows else None))
            if len(recent)<21 or not rows or rows[-1]["date"]!=TARGET:
                rec["classification"]="QFQ_INSUFFICIENT_OR_STALE"
            elif any(not valid_geometry(x) for x in recent):
                rec["classification"]="QFQ_GEOMETRY_INVALID"
            elif any(recent[i]["date"]>=recent[i+1]["date"] for i in range(len(recent)-1)):
                rec["classification"]="QFQ_DUPLICATE_OR_UNSORTED"
            else:
                rec["classification"]="RECOVERABLE_BY_TENCENT_QFQ_FALLBACK"
                rec["recent21_sha256"]=hashlib.sha256(json.dumps(recent,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        except Exception as exc:
            rec.update(classification="QFQ_FETCH_OR_PARSE_FAILURE",error=type(exc).__name__+":"+str(exc)[:180])
        with lock: out.append(rec)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one,targets))
    out.sort(key=lambda x:x["code"])
    counts={}
    for r in out: counts[r["classification"]]=counts.get(r["classification"],0)+1
    report={
      "schema_version":5,
      "run_id":"TRI-DSA-DAT-20260914-006-GEOMETRY-QFQ-R5",
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "source_integrity_sha256":hashlib.sha256(a.integrity.read_bytes()).hexdigest(),
      "original_recovery_denominator":253,
      "geometry_denominator":114,
      "target":TARGET,
      "classification_counts":counts,
      "rows":out,
      "model_http_requests":0,
      "paid_data_used":False,
      "historical_inputs_rewritten":False,
      "frozen_predictions_rewritten":False
    }
    if len(out)!=114 or sum(counts.values())!=114: raise ValueError("diagnostic_accounting_failure")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print("RUN006_QFQ_RECOVERY_R5",json.dumps(counts,ensure_ascii=False),flush=True)

if __name__=="__main__": main()
