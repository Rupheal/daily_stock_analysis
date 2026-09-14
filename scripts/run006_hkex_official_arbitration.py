"""Run006 B1 recovery: official HKEX arbitration for the 246 engineering isolates.

Fetches the 21 Main Board Daily Quotations pages from 2026-08-14 through
2026-09-11, parses raw official OHLC/volume, and compares them with fresh Yahoo
unadjusted and Tencent qfq observations. This is diagnostic evidence only: no bar
is repaired, no tolerance is promoted to production, and no model is called.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import yfinance as yf

SESSIONS = [
    "2026-08-14","2026-08-17","2026-08-18","2026-08-19","2026-08-20","2026-08-21",
    "2026-08-24","2026-08-25","2026-08-26","2026-08-27","2026-08-28","2026-08-31",
    "2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08",
    "2026-09-09","2026-09-10","2026-09-11",
]
TARGET = "2026-09-11"
EXPECTED_COUNTS={"independent_daily_disagreement":132,"ValueError:invalid_daily_geometry":114,"ValueError:missing_latest_session_or_21_bar_history":7}
LINE1 = re.compile(r"^\s*\*?\s*(?P<code>\d{1,5})\s+(?P<name>.+?)\s+(?P<cur>HKD|RMB|USD)\s+(?P<prev>[0-9.]+|-)\s+(?P<ask>[0-9.]+|-)\s+(?P<high>[0-9.]+|-)\s+(?P<shares>[0-9,]+|-)\s*$")
LINE2 = re.compile(r"^\s*(?P<close>[0-9.]+|-)\s+(?P<bid>[0-9.]+|-)\s+(?P<low>[0-9.]+|-)\s+(?P<turnover>[0-9,]+|-)\s*$")
TAG = re.compile(r"<[^>]+>")


def sha_bytes(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def hk(code: str) -> str: return "HK"+str(code).upper().removeprefix("HK").zfill(5)
def yf_symbol(code: str) -> str:
    b=hk(code)[2:].lstrip("0") or "0"; return b.zfill(4)+".HK"
def tencent_symbol(code: str) -> str: return hk(code).lower()

def n(text: str):
    if text == "-": return None
    return float(text.replace(",",""))

def valid_bar(row: dict | None) -> bool:
    if not row: return False
    try: o,h,l,c,v=[float(row[k]) for k in ("open","high","low","close","volume")]
    except Exception: return False
    eps=max(1e-12,max(abs(o),abs(h),abs(l),abs(c))*1e-12)
    return l <= min(o,c)+eps and max(o,c) <= h+eps and l>0 and v>=0

def fetch_hkex(day: str) -> tuple[bytes,str]:
    compact=day.replace("-","")[2:]
    url=f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{compact}e.htm"
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=45) as r: b=r.read(8_000_000)
    return b,url

def parse_hkex_page(b: bytes) -> dict[str,dict]:
    text=html.unescape(b.decode("latin1","ignore")); text=TAG.sub("",text).replace("\r","")
    start=text.find("PRV.CLO./")
    if start<0: raise ValueError("quotation_header_missing")
    stop=text.find("SALES RECORD",start); section=text[start:stop if stop>=0 else len(text)]
    lines=section.splitlines(); out={}
    for i,line in enumerate(lines[:-1]):
        m=LINE1.match(line)
        if not m: continue
        m2=LINE2.match(lines[i+1])
        if not m2: continue
        code=hk(m.group("code"))
        # Raw official opening price is not printed in the compact Daily Quotations row.
        # Previous close/high/low/close/shares remain official arbitration fields.
        out[code]={"code":code,"name":" ".join(m.group("name").split()),"currency":m.group("cur"),
                   "previous_close":n(m.group("prev")),"high":n(m.group("high")),"low":n(m2.group("low")),
                   "close":n(m2.group("close")),"volume":n(m.group("shares")),"turnover":n(m2.group("turnover"))}
    return out

def yahoo_unadjusted(code: str) -> dict[str,dict]:
    f=yf.Ticker(yf_symbol(code)).history(start="2026-08-13",end="2026-09-12",auto_adjust=False,actions=True,repair=False)
    out={}
    for idx,r in f.iterrows():
        d=str(idx)[:10]
        if d not in SESSIONS: continue
        out[d]={"open":float(r["Open"]),"high":float(r["High"]),"low":float(r["Low"]),"close":float(r["Close"]),"volume":float(r["Volume"]),
                "dividends":float(r["Dividends"]) if "Dividends" in f.columns else 0.0,
                "stock_splits":float(r["Stock Splits"]) if "Stock Splits" in f.columns else 0.0}
    return out

def tencent_qfq(code: str) -> tuple[bytes,dict[str,dict]]:
    sym=tencent_symbol(code); url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":f"{sym},day,,,180,qfq"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=30) as r: b=r.read(2_000_000)
    p=json.loads(b); item=(p.get("data") or {}).get(sym) or {}; rows=item.get("qfqday") or item.get("day") or []
    out={}
    for z in rows:
        if not isinstance(z,list) or len(z)<6 or str(z[0]) not in SESSIONS: continue
        out[str(z[0])] = {"open":float(z[1]),"close":float(z[2]),"high":float(z[3]),"low":float(z[4]),"volume":float(z[5])}
    return b,out

def rel(a,b):
    if a is None or b is None: return None
    return abs(float(a)-float(b))/max(abs(float(b)),1e-12)

def factor_spread(official: dict, qfq: dict) -> dict:
    ratios=[]
    for field in ("high","low","close"):
        a=qfq.get(field); b=official.get(field)
        if a is not None and b not in (None,0): ratios.append(float(a)/float(b))
    if not ratios: return {"ratio_count":0,"mean_factor":None,"max_relative_dispersion":None}
    mean=sum(ratios)/len(ratios)
    disp=max(abs(x-mean)/max(abs(mean),1e-12) for x in ratios)
    return {"ratio_count":len(ratios),"mean_factor":mean,"max_relative_dispersion":disp}

def one(code: str, reason: str, official_by_day: dict[str,dict[str,dict]]) -> dict:
    rec={"code":code,"original_reason":reason,"status":"DIAGNOSTIC_ERROR"}
    try:
        y=yahoo_unadjusted(code); tb,t=tencent_qfq(code)
        days=[]
        for d in SESSIONS:
            off=official_by_day[d].get(code); yr=y.get(d); tq=t.get(d)
            row={"date":d,"official":off,"yahoo_raw":yr,"tencent_qfq":tq,
                 "yahoo_geometry_valid":valid_bar(yr),"tencent_geometry_valid":valid_bar(tq)}
            if off:
                row["yahoo_vs_official"]={f:rel((yr or {}).get(f),off.get(f)) for f in ("high","low","close","volume")}
                row["tencent_qfq_factor"] = factor_spread(off,tq or {})
                row["tencent_volume_vs_official_rel"] = rel((tq or {}).get("volume"),off.get("volume"))
            days.append(row)
        off_count=sum(r["official"] is not None for r in days); y_count=sum(r["yahoo_raw"] is not None for r in days); t_count=sum(r["tencent_qfq"] is not None for r in days)
        y_price=[v for r in days for k,v in (r.get("yahoo_vs_official") or {}).items() if k!="volume" and v is not None]
        y_vol=[(r.get("yahoo_vs_official") or {}).get("volume") for r in days if (r.get("yahoo_vs_official") or {}).get("volume") is not None]
        fdisp=[(r.get("tencent_qfq_factor") or {}).get("max_relative_dispersion") for r in days if (r.get("tencent_qfq_factor") or {}).get("max_relative_dispersion") is not None]
        tvol=[r.get("tencent_volume_vs_official_rel") for r in days if r.get("tencent_volume_vs_official_rel") is not None]
        rec.update({"status":"OK","official_count":off_count,"yahoo_count":y_count,"tencent_qfq_count":t_count,
                    "yahoo_valid_count":sum(r["yahoo_geometry_valid"] for r in days),"tencent_valid_count":sum(r["tencent_geometry_valid"] for r in days),
                    "yahoo_official_price_max_rel_diff":max(y_price) if y_price else None,"yahoo_official_price_median_rel_diff":sorted(y_price)[len(y_price)//2] if y_price else None,
                    "yahoo_official_volume_max_rel_diff":max(y_vol) if y_vol else None,
                    "tencent_qfq_same_day_factor_max_dispersion":max(fdisp) if fdisp else None,
                    "tencent_official_volume_max_rel_diff":max(tvol) if tvol else None,
                    "tencent_payload_sha256":sha_bytes(tb),"days":days})
    except Exception as exc: rec["error"]=type(exc).__name__+":"+str(exc)[:200]
    return rec

def main():
    p=argparse.ArgumentParser(); p.add_argument("--integrity",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--raw-dir",type=Path,required=True); p.add_argument("--workers",type=int,default=8); a=p.parse_args()
    x=json.loads(a.integrity.read_text())
    if x.get("denominator")!=660 or x.get("isolated")!=253 or x.get("reasons")!=EXPECTED_COUNTS: raise SystemExit("frozen denominator mismatch")
    items=[r for r in x["coverage"] if r.get("reason") in {"independent_daily_disagreement","ValueError:invalid_daily_geometry"}]
    if len(items)!=246: raise SystemExit("engineering isolate denominator mismatch")
    a.raw_dir.mkdir(parents=True,exist_ok=True); official_by_day={}; page_receipts={}
    for d in SESSIONS:
        b,url=fetch_hkex(d); (a.raw_dir/f"hkex-{d}.htm").write_bytes(b); official_by_day[d]=parse_hkex_page(b); page_receipts[d]={"url":url,"bytes":len(b),"sha256":sha_bytes(b),"parsed_count":len(official_by_day[d])}
        if len(official_by_day[d])<500: raise SystemExit(f"implausibly_small_official_page:{d}:{len(official_by_day[d])}")
    rows=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        fs=[pool.submit(one,r["code"],r["reason"],official_by_day) for r in items]
        for f in as_completed(fs): rows.append(f.result())
    rows.sort(key=lambda r:r["code"]); ok=[r for r in rows if r["status"]=="OK"]
    summary={"ok":len(ok),"errors":len(rows)-len(ok),
             "official_complete_21":sum(r.get("official_count")==21 for r in ok),"tencent_complete_21":sum(r.get("tencent_qfq_count")==21 for r in ok),"yahoo_complete_21":sum(r.get("yahoo_count")==21 for r in ok),
             "tencent_full_geometry_21":sum(r.get("tencent_valid_count")==21 for r in ok),"yahoo_full_geometry_21":sum(r.get("yahoo_valid_count")==21 for r in ok)}
    out={"schema_version":1,"run_id":"TRI-DSA-DAT-20260914-006-R3-HKEX-ARBITRATION","generated_at":datetime.now(timezone.utc).isoformat(),"original_recovery_denominator":253,"track_denominator":246,"model_http_requests":0,"paid_data_used":False,"source_integrity_sha256":sha(a.integrity),"sessions":SESSIONS,"official_page_receipts":page_receipts,"summary":summary,"rows":rows}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print("RUN006_HKEX_ARBITRATION",json.dumps({"denominator":246,"summary":summary},ensure_ascii=False),flush=True)
if __name__=="__main__": main()
