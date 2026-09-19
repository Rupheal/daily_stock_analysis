#!/usr/bin/env python3
"""Build current-session U45 technical/member and close receipts from public daily bars.

This production builder never carries forward stale news/capital assertions.
Only identity/eligibility/board-lot metadata is inherited from the frozen U45
universe. Price/technical facts are recomputed for the requested session.
"""
from __future__ import annotations
import argparse,json,math,hashlib
from pathlib import Path
from statistics import mean

VERSION="U_PRODUCTION_DAILY_MEMBER_v1"

def finite(x):
    try:v=float(x)
    except Exception:return None
    return v if math.isfinite(v) else None

def rsi14(closes):
    if len(closes)<15:return None
    gains=[];losses=[]
    for a,b in zip(closes[-15:-1],closes[-14:]):
        d=b-a;gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains)/14;al=sum(losses)/14
    if al==0:return 100.0
    rs=ag/al;return 100-(100/(1+rs))

def ema(vals,n):
    if len(vals)<n:return None
    k=2/(n+1);x=sum(vals[:n])/n
    for v in vals[n:]:x=v*k+x*(1-k)
    return x

def macd(closes):
    if len(closes)<35:return None
    e12=ema(closes,12);e26=ema(closes,26)
    # compact deterministic approximation of current DIF/signal
    difs=[]
    for i in range(26,len(closes)+1):
        a=ema(closes[:i],12);b=ema(closes[:i],26)
        if a is not None and b is not None:difs.append(a-b)
    sig=ema(difs,9)
    if e12 is None or e26 is None or sig is None:return None
    dif=e12-e26
    return {"dif":dif,"signal":sig,"histogram_2x":2*(dif-sig)}

def trend(closes):
    if len(closes)<20:return "UNKNOWN"
    m5=mean(closes[-5:]);m10=mean(closes[-10:]);m20=mean(closes[-20:])
    if m5>m10>m20:return "BULLISH_MA_ORDER"
    if m5<m10<m20:return "BEARISH_MA_ORDER"
    return "MIXED_MA_ORDER"

def get_history(code,target):
    import yfinance as yf
    from datetime import date,timedelta
    ticker=f"{code}.HK"
    end=(date.fromisoformat(target)+timedelta(days=1)).isoformat()
    start=(date.fromisoformat(target)-timedelta(days=120)).isoformat()
    df=yf.download(ticker,start=start,end=end,interval="1d",auto_adjust=False,progress=False,threads=False)
    if df is None or df.empty:return []
    out=[]
    for ts,row in df.iterrows():
        d=ts.date().isoformat()
        vals={k:finite(row.get(k)) for k in ("Open","High","Low","Close","Volume")}
        if all(vals[k] is not None for k in vals):
            out.append({"date":d,"open":vals["Open"],"high":vals["High"],"low":vals["Low"],
                        "close":vals["Close"],"volume":vals["Volume"]})
    return out

def facts(rows):
    closes=[x["close"] for x in rows];vol=[x["volume"] for x in rows]
    cur=rows[-1]
    def ret(n):
        return (closes[-1]/closes[-1-n]-1)*100 if len(closes)>n and closes[-1-n]>0 else None
    prev5=mean(vol[-6:-1]) if len(vol)>=6 else None
    m=macd(closes)
    return {
      "close":cur["close"],"return_1d_pct":ret(1),"return_5d_pct":ret(5),"return_20d_pct":ret(20),
      "ma5":mean(closes[-5:]) if len(closes)>=5 else None,
      "ma10":mean(closes[-10:]) if len(closes)>=10 else None,
      "ma20":mean(closes[-20:]) if len(closes)>=20 else None,
      "volume_shares":cur["volume"],
      "volume_vs_previous5":cur["volume"]/prev5 if prev5 and prev5>0 else None,
      "observed_support20":min(x["low"] for x in rows[-20:]) if len(rows)>=20 else None,
      "observed_resistance20":max(x["high"] for x in rows[-20:]) if len(rows)>=20 else None,
      "turnover_hkd":None,"turnover_reason":"Not inferred from close*volume.",
      "rsi14":rsi14(closes),"macd":m or {"dif":None,"signal":None,"histogram_2x":None},
      "indicator_history_count":len(rows),"rsi_seed":"Wilder14 current rolling window",
      "trend":trend(closes),
    }

def build(universe,target):
    members=universe.get("members") or []
    if len(members)!=45:raise ValueError("U45_UNIVERSE_DENOMINATOR_MISMATCH")
    reports=[];close=[];fail=[]
    for m in members:
        code=str(m["code"]).zfill(5);rows=get_history(code,target)
        current=[x for x in rows if x["date"]==target]
        valid=bool(current and len(rows)>=21)
        if not valid:
            fail.append(code)
            close.append({"code":code,"official_name":m.get("official_name"),"target_session":target,
                          "current_valid_bar":False,"latest_date":rows[-1]["date"] if rows else None,
                          "open":None,"high":None,"low":None,"close":None,"volume":None})
            continue
        current_row=current[-1]
        # trim at target to prevent future contamination
        rows=[x for x in rows if x["date"]<=target]
        f=facts(rows)
        close.append({"code":code,"official_name":m.get("official_name"),"target_session":target,
                      "current_valid_bar":True,"latest_date":target,
                      **{k:current_row[k] for k in ("open","high","low","close","volume")}})
        reports.append({
          "code":code,"name":m.get("user_alias") or m.get("official_name"),
          "status":"PRODUCTION_TECHNICAL_FACT_REPORT",
          "action":"OBSERVE","score":None,"rank":None,"facts":f,"plan":{},
          "findings":["CURRENT_NEWS_NOT_AUTOMATICALLY_SOURCE_BOUND","CURRENT_CAPITAL_NOT_AUTOMATICALLY_SOURCE_BOUND"],
          "data_session":target,"report_available_at":None,"formal_buy_accepted":False,
          "O_results_used":False,"history_source":"YFinance daily raw",
          "history_bars":len(rows),
          "news":{"state":"NEWS_EVIDENCE_MISSING_CURRENT_SESSION","retrieval_ready":False,
                  "verified_source_urls":[],"scope":"No stale issuer event carried forward."},
          "capital":{"status":"MISSING_CURRENT_SESSION","net_buy_hkd":None,"date":target,
                     "persistence":"UNKNOWN","ultimate_investor_identity":"NOT_PROVEN"},
          "evidence_ids":[f"price:{code}",f"technical:{code}"]
        })
    member_receipt={"schema_version":1,"run_id":"DSA-U-MEMBER-"+target.replace("-",""),
                    "target_session":target,"U_denominator":45,"members":reports,
                    "failed_codes":fail,"current_member_count":len(reports),
                    "model_http_requests":0,"real_orders":0}
    close_receipt={"schema_version":1,"run_id":"DSA-U-CLOSE-"+target.replace("-",""),
                   "target_session":target,"denominator":45,
                   "current_valid_count":sum(x["current_valid_bar"] for x in close),
                   "status":"PASS_CURRENT_SESSION_FACT_REFRESH" if not fail else "PARTIAL_CURRENT_SESSION_FACT_REFRESH",
                   "facts":close,"model_http_requests":0,"real_orders":0}
    return member_receipt,close_receipt

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--target-session",required=True);ap.add_argument("--member-out",type=Path,required=True)
    ap.add_argument("--close-out",type=Path,required=True);a=ap.parse_args()
    u=json.loads(a.universe.read_text());m,c=build(u,a.target_session)
    a.member_out.parent.mkdir(parents=True,exist_ok=True);a.close_out.parent.mkdir(parents=True,exist_ok=True)
    a.member_out.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n")
    a.close_out.write_text(json.dumps(c,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"member_count":m["current_member_count"],"close_valid":c["current_valid_count"],"failed":m["failed_codes"]}))
if __name__=="__main__":main()
