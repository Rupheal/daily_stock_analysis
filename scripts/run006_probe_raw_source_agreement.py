"""Run006 B1 recovery: diagnose 132 adjusted-source disagreements on raw OHLCV.

The original gate compared Yahoo auto-adjusted values against Tencent qfq values.
This diagnostic refetches unadjusted Yahoo and raw Tencent daily data, preserves the
132-name denominator, and reports differences without choosing a tolerance or repairing data.
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

import yfinance as yf

TARGET="2026-09-11"
EXPECTED_COUNTS={"independent_daily_disagreement":132,"ValueError:invalid_daily_geometry":114,"ValueError:missing_latest_session_or_21_bar_history":7}
FIELDS=("open","high","low","close","volume")


def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def symbol(code:str)->str: return "hk"+code.upper().removeprefix("HK").zfill(5)
def yf_symbol(code:str)->str:
    b=code.upper().removeprefix("HK").lstrip("0") or "0"; return b.zfill(4)+".HK"

def valid_bar(r):
    try: o,h,l,c,v=[float(r[k]) for k in FIELDS]
    except Exception: return False
    eps=max(1e-12,max(abs(o),abs(h),abs(l),abs(c))*1e-12)
    return l<=min(o,c)+eps and max(o,c)<=h+eps and l>0 and v>=0

def yahoo_rows(code:str):
    f=yf.Ticker(yf_symbol(code)).history(period="3mo",auto_adjust=False,actions=True,repair=False)
    out=[]
    for idx,r in f.iterrows():
        d=str(idx)[:10]
        if d>TARGET: continue
        row={"date":d}
        for src,dst in (("Open","open"),("High","high"),("Low","low"),("Close","close"),("Volume","volume")):
            row[dst]=float(r[src])
        for src,dst in (("Dividends","dividends"),("Stock Splits","stock_splits")):
            row[dst]=float(r[src]) if src in f.columns else 0.0
        out.append(row)
    return out

def tencent_raw(code:str):
    param=f"{symbol(code)},day,,,180"
    url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":param})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=30) as resp: raw=resp.read(2_000_000)
    payload=json.loads(raw); item=(payload.get("data") or {}).get(symbol(code)) or {}; rows=item.get("day") or []
    out=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<6 or str(r[0])>TARGET: continue
        out.append({"date":str(r[0]),"open":r[1],"close":r[2],"high":r[3],"low":r[4],"volume":r[5]})
    return raw,out

def one(item):
    code=item["code"]; rec={"code":code,"status":"DIAGNOSTIC_ERROR","original_adjusted_mismatch_count":len((item.get("audit") or {}).get("mismatches") or [])}
    try:
        y=yahoo_rows(code); tbytes,t=tencent_raw(code)
        yl={r["date"]:r for r in y}; tl={r["date"]:r for r in t}; common=sorted(set(yl)&set(tl)); recent=common[-21:]
        diffs=[]
        for d in recent:
            for field in FIELDS:
                a=float(yl[d][field]); b=float(tl[d][field]); absd=abs(a-b); reld=absd/max(abs(b),1e-12)
                diffs.append({"date":d,"field":field,"yahoo_raw":a,"tencent_raw":b,"abs_diff":absd,"rel_diff":reld})
        price=[d for d in diffs if d["field"]!="volume"]; vol=[d for d in diffs if d["field"]=="volume"]
        yrecent=[yl[d] for d in recent]; trecent=[tl[d] for d in recent]
        corp=[{"date":r["date"],"dividends":r.get("dividends",0.0),"stock_splits":r.get("stock_splits",0.0)} for r in y if r.get("dividends") or r.get("stock_splits")]
        rec.update({
            "status":"OK","yahoo_row_count":len(y),"tencent_row_count":len(t),"common_count":len(common),"recent_common_count":len(recent),
            "latest_common_date":recent[-1] if recent else None,"yahoo_recent_geometry_valid":len(yrecent)==21 and all(valid_bar(r) for r in yrecent),
            "tencent_recent_geometry_valid":len(trecent)==21 and all(valid_bar(r) for r in trecent),
            "price_max_abs_diff":max((d["abs_diff"] for d in price),default=None),"price_median_abs_diff":sorted([d["abs_diff"] for d in price])[len(price)//2] if price else None,
            "price_max_rel_diff":max((d["rel_diff"] for d in price),default=None),"price_median_rel_diff":sorted([d["rel_diff"] for d in price])[len(price)//2] if price else None,
            "volume_max_abs_diff":max((d["abs_diff"] for d in vol),default=None),
            "raw_price_fields_with_abs_diff_gt_0_005":sum(d["abs_diff"]>0.005 for d in price),
            "raw_price_fields_with_rel_diff_gt_0_001":sum(d["rel_diff"]>0.001 for d in price),
            "corporate_actions":corp,"tencent_raw_sha256":hashlib.sha256(tbytes).hexdigest(),"diffs":diffs,
        })
    except Exception as exc: rec["error"]=type(exc).__name__+":"+str(exc)[:180]
    return rec

def main():
    p=argparse.ArgumentParser(); p.add_argument("--integrity",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--workers",type=int,default=8); a=p.parse_args()
    x=json.loads(a.integrity.read_text())
    if x.get("denominator")!=660 or x.get("isolated")!=253 or x.get("reasons")!=EXPECTED_COUNTS: raise SystemExit("frozen denominator mismatch")
    items=[r for r in x["coverage"] if r.get("reason")=="independent_daily_disagreement"]
    if len(items)!=132: raise SystemExit("disagreement denominator mismatch")
    rows=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        fs=[pool.submit(one,r) for r in items]
        for f in as_completed(fs): rows.append(f.result())
    rows.sort(key=lambda r:r["code"])
    ok=[r for r in rows if r["status"]=="OK"]
    summary={
      "ok":len(ok),"errors":len(rows)-len(ok),
      "both_sources_complete_valid_21":sum(r.get("recent_common_count")==21 and r.get("latest_common_date")==TARGET and r.get("yahoo_recent_geometry_valid") and r.get("tencent_recent_geometry_valid") for r in ok),
      "max_raw_rel_diff_le_0_001":sum((r.get("price_max_rel_diff") is not None and r["price_max_rel_diff"]<=0.001) for r in ok),
      "max_raw_rel_diff_le_0_005":sum((r.get("price_max_rel_diff") is not None and r["price_max_rel_diff"]<=0.005) for r in ok),
      "has_yahoo_corporate_action":sum(bool(r.get("corporate_actions")) for r in ok),
    }
    out={"schema_version":1,"run_id":"TRI-DSA-DAT-20260914-006-R2-RAW-AGREEMENT","generated_at":datetime.now(timezone.utc).isoformat(),"original_recovery_denominator":253,"track_denominator":132,"model_http_requests":0,"paid_data_used":False,"source_integrity_sha256":sha(a.integrity),"summary":summary,"rows":rows}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print("RUN006_RAW_AGREEMENT",json.dumps({"denominator":132,"summary":summary},ensure_ascii=False),flush=True)

if __name__=="__main__": main()
