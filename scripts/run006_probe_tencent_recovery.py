"""Run006 B1 recovery: Tencent arbitration for Yahoo geometry/history isolates.

Uses Tencent's public HK K-line endpoint in both raw `day` and qfq modes. The probe
never modifies retained data and performs no model calls. Recovery candidates require
an intact frozen denominator and a complete valid 21-session Tencent qfq window.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EXPECTED_COUNTS = {
    "independent_daily_disagreement": 132,
    "ValueError:invalid_daily_geometry": 114,
    "ValueError:missing_latest_session_or_21_bar_history": 7,
}
TARGET = "2026-09-11"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol(code: str) -> str:
    return "hk" + code.upper().removeprefix("HK").zfill(5)


def fetch(code: str, qfq: bool) -> tuple[bytes, dict]:
    mode = "qfq" if qfq else ""
    param = f"{symbol(code)},day,,,180" + (",qfq" if qfq else "")
    url = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?" + urlencode({"param": param})
    req = Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"})
    with urlopen(req, timeout=30) as resp:
        raw = resp.read(2_000_000)
    return raw, json.loads(raw)


def parse(payload: dict, code: str, prefer_qfq: bool) -> tuple[str | None, list[dict]]:
    item = (payload.get("data") or {}).get(symbol(code)) or {}
    keys = ["qfqday","day"] if prefer_qfq else ["day","qfqday"]
    key = next((k for k in keys if item.get(k)), None)
    out=[]
    for r in item.get(key, []) if key else []:
        if not isinstance(r,list) or len(r)<6: continue
        out.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    return key, out


def valid_bar(r: dict) -> bool:
    try:
        o,h,l,c,v=[float(r[k]) for k in ("open","high","low","close","volume")]
    except Exception:
        return False
    eps=max(1e-12, max(abs(o),abs(h),abs(l),abs(c))*1e-12)
    return l <= min(o,c)+eps and max(o,c) <= h+eps and l>0 and v>=0


def validate_window(rows: list[dict]) -> dict:
    rows=[r for r in rows if r["date"]<=TARGET]
    dates=[r["date"] for r in rows]
    unique_sorted=(dates==sorted(dates) and len(dates)==len(set(dates)))
    recent=rows[-21:] if len(rows)>=21 else rows
    invalid=[r["date"] for r in recent if not valid_bar(r)]
    return {
        "row_count_to_target":len(rows),"latest_date":dates[-1] if dates else None,
        "recent_count":len(recent),"unique_sorted":unique_sorted,"invalid_recent_dates":invalid,
        "complete_21_to_target":len(recent)==21 and (dates[-1] if dates else None)==TARGET and unique_sorted and not invalid,
    }


def one(item: dict) -> dict:
    code=item["code"]; reason=item["reason"]
    rec={"code":code,"original_reason":reason,"status":"DIAGNOSTIC_ERROR"}
    try:
        raw_bytes, raw_payload=fetch(code,False)
        qfq_bytes, qfq_payload=fetch(code,True)
        raw_key, raw_rows=parse(raw_payload,code,False)
        qfq_key, qfq_rows=parse(qfq_payload,code,True)
        raw_eval=validate_window(raw_rows); qfq_eval=validate_window(qfq_rows)
        failing_date=(item.get("invalid_bar") or {}).get("date")
        raw_bad=next((r for r in raw_rows if r["date"]==failing_date),None) if failing_date else None
        qfq_bad=next((r for r in qfq_rows if r["date"]==failing_date),None) if failing_date else None
        if reason=="ValueError:invalid_daily_geometry":
            if raw_bad and qfq_bad and valid_bar(raw_bad) and valid_bar(qfq_bad) and qfq_eval["complete_21_to_target"]:
                cls="RECOVERABLE_BY_TENCENT_FULL_WINDOW"
            elif qfq_eval["complete_21_to_target"]:
                cls="TENCENT_WINDOW_VALID_BUT_FAILING_DATE_REVIEW"
            else:
                cls="TENCENT_NOT_SUFFICIENT_FOR_GEOMETRY_RECOVERY"
        else:
            if qfq_eval["complete_21_to_target"]:
                cls="PROVIDER_GAP_RECOVERABLE_BY_TENCENT"
            else:
                cls="RETAIN_HISTORY_OR_TRADING_GAP"
        rec.update({
            "status":"OK","classification":cls,
            "raw_endpoint_sha256":hashlib.sha256(raw_bytes).hexdigest(),
            "qfq_endpoint_sha256":hashlib.sha256(qfq_bytes).hexdigest(),
            "raw_key":raw_key,"qfq_key":qfq_key,
            "raw_window":raw_eval,"qfq_window":qfq_eval,
            "failing_date":failing_date,
            "raw_failing_bar":raw_bad,"raw_failing_bar_valid":valid_bar(raw_bad) if raw_bad else None,
            "qfq_failing_bar":qfq_bad,"qfq_failing_bar_valid":valid_bar(qfq_bad) if qfq_bad else None,
        })
    except Exception as exc:
        rec["error"]=type(exc).__name__+":"+str(exc)[:180]
    return rec


def main():
    p=argparse.ArgumentParser(); p.add_argument("--integrity",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--workers",type=int,default=8)
    a=p.parse_args(); x=json.loads(a.integrity.read_text())
    if x.get("denominator")!=660 or x.get("isolated")!=253 or x.get("reasons")!=EXPECTED_COUNTS: raise SystemExit("frozen denominator mismatch")
    wanted={"ValueError:invalid_daily_geometry","ValueError:missing_latest_session_or_21_bar_history"}
    items=[r for r in x["coverage"] if r.get("reason") in wanted]
    if len(items)!=121: raise SystemExit("track denominator mismatch")
    rows=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs=[pool.submit(one,r) for r in items]
        for f in as_completed(futs): rows.append(f.result())
    rows.sort(key=lambda r:r["code"])
    counts={}
    for r in rows:
        k=r.get("classification") if r.get("status")=="OK" else "DIAGNOSTIC_ERROR"; counts[k]=counts.get(k,0)+1
    out={"schema_version":1,"run_id":"TRI-DSA-DAT-20260914-006-R1-TENCENT-ARBITRATION","generated_at":datetime.now(timezone.utc).isoformat(),"model_http_requests":0,"paid_data_used":False,"original_recovery_denominator":253,"track_denominator":121,"source_integrity_sha256":sha(a.integrity),"classification_counts":counts,"rows":rows}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print("RUN006_TENCENT_ARBITRATION",json.dumps({"denominator":121,"classification_counts":counts},ensure_ascii=False),flush=True)

if __name__=="__main__": main()
