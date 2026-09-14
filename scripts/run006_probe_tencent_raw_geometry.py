"""Probe raw Tencent daily bars for the 114 frozen Yahoo geometry isolates.

Diagnostic only: never rewrites historical data or model inputs.
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


def canonical(code: str) -> str:
    return "HK"+str(code).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def valid_geometry(row: dict) -> bool:
    try:
        v={k:Decimal(str(row[k])) for k in FIELDS}
    except Exception:
        return False
    return all(x.is_finite() for x in v.values()) and 0 < v["low"] <= min(v["open"],v["close"]) <= max(v["open"],v["close"]) <= v["high"] and v["volume"] >= 0


def fetch_raw(code: str):
    code=canonical(code)
    url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":code.lower()+",day,,,180"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=25) as resp:
        raw=resp.read(2_000_000)
    payload=json.loads(raw)
    item=payload.get("data",{}).get(code.lower()) or {}
    rows=item.get("day")
    if not isinstance(rows,list):
        raise ValueError("raw_day_missing")
    parsed=[]
    for r in rows:
        if len(r)<6: continue
        parsed.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    return url, hashlib.sha256(raw).hexdigest(), parsed


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--integrity",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    src=json.loads(a.integrity.read_text())
    assert src["track"]=="O" and src["denominator"]==660
    targets=[]
    for r in src["coverage"]:
        if r.get("reason","").endswith("invalid_daily_geometry") or "invalid_daily_geometry" in r.get("reason",""):
            if not r.get("invalid_bar") or not r["invalid_bar"].get("date"):
                raise ValueError("geometry_isolate_missing_public_row")
            targets.append(r)
    if len(targets)!=114: raise ValueError(f"expected_114_geometry_isolates_got_{len(targets)}")
    out=[]; lock=Lock()
    def one(r):
        code=canonical(r["code"]); day=r["invalid_bar"]["date"]
        rec={"code":code,"failing_date":day,"frozen_invalid_bar":r["invalid_bar"]}
        try:
            url,sha,rows=fetch_raw(code)
            by={x["date"]:x for x in rows}
            bar=by.get(day)
            rec.update(url=url,response_sha256=sha,raw_session_count=len(rows))
            if bar is None:
                rec.update(classification="TENCENT_RAW_SESSION_MISSING",raw_bar=None)
            elif not valid_geometry(bar):
                rec.update(classification="TENCENT_RAW_GEOMETRY_INVALID",raw_bar=bar)
            else:
                rec.update(classification="TENCENT_RAW_VALID_ALTERNATIVE",raw_bar=bar)
        except Exception as exc:
            rec.update(classification="TENCENT_RAW_FETCH_OR_PARSE_FAILURE",error=type(exc).__name__+":"+str(exc)[:160])
        with lock: out.append(rec)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one,targets))
    out.sort(key=lambda x:x["code"])
    counts={}
    for r in out: counts[r["classification"]]=counts.get(r["classification"],0)+1
    report={
      "schema_version":1,
      "run_id":"TRI-DSA-DAT-20260914-006-GEOMETRY-TENCENT-RAW-R1",
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "source_integrity_sha256":hashlib.sha256(a.integrity.read_bytes()).hexdigest(),
      "original_recovery_denominator":253,
      "geometry_denominator":114,
      "classification_counts":counts,
      "rows":out,
      "model_http_requests":0,
      "paid_data_used":False,
      "historical_inputs_rewritten":False,
    }
    if len(out)!=114 or sum(counts.values())!=114: raise ValueError("diagnostic_accounting_failure")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print("RUN006_TENCENT_RAW_GEOMETRY_PROBE",json.dumps(counts,ensure_ascii=False),flush=True)

if __name__=="__main__": main()
