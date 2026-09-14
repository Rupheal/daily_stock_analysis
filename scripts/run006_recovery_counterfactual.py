"""Run006 deterministic counterfactual B1 recovery acceptance.

Uses the frozen O660 denominator. It never changes Run005 A0/A3 predictions and makes
zero model calls. Original 407 passed names use the frozen database; recovery candidates
use Tencent qfq under the frozen Run006 routing contract.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.run004_pool_safe_deepseek import canonical_code, technical_features
from src.services.dsa_ranking_envelope import canonical_hash

TARGET="2026-09-11"


def load_json(path): return json.loads(Path(path).read_text(encoding="utf-8"))


def qfq_rows(code):
    code=canonical_code(code)
    url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?"+urlencode({"param":code.lower()+",day,,,180,qfq"})
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}),timeout=25) as resp:
        raw=resp.read(2_000_000)
    payload=json.loads(raw); item=(payload.get("data") or {}).get(code.lower()) or {}; source=item.get("qfqday") or item.get("day") or []
    rows=[]
    for r in source:
        if not isinstance(r,list) or len(r)<6: continue
        rows.append({"date":str(r[0]),"open":float(r[1]),"close":float(r[2]),"high":float(r[3]),"low":float(r[4]),"volume":float(r[5])})
    rows=[r for r in rows if r["date"]<=TARGET]
    if len(rows)<21 or rows[-1]["date"]!=TARGET: raise ValueError("fallback_missing_target_complete_21bar_history")
    rows=rows[-21:]
    for i,r in enumerate(rows):
        if i and rows[i-1]["date"]>=r["date"]: raise ValueError("fallback_unsorted_history")
        if not (0<r["low"]<=min(r["open"],r["close"])<=max(r["open"],r["close"])<=r["high"] and r["volume"]>=0): raise ValueError("fallback_invalid_geometry")
    return hashlib.sha256(raw).hexdigest(),rows


def ret(closes,n): return (closes[-1]/closes[-1-n]-1)*100 if closes[-1-n]>0 else None


def fallback_features(code, rows):
    closes=[r["close"] for r in rows]; highs=[r["high"] for r in rows[-20:]]; lows=[r["low"] for r in rows[-20:]]; vols=[r["volume"] for r in rows]
    def ma(n): return round(sum(closes[-n:])/n,2)
    ma5,ma10,ma20=ma(5),ma(10),ma(20); close=closes[-1]
    prev5=vols[-6:-1]; vr=round(vols[-1]/(sum(prev5)/len(prev5)),2) if prev5 and sum(prev5)>0 else 1.0
    returns=[(b/a-1)*100 for a,b in zip(closes[-21:-1],closes[-20:]) if a>0]; mean=sum(returns)/len(returns) if returns else 0.0; variance=sum((x-mean)**2 for x in returns)/len(returns) if returns else 0.0
    pos=(close-min(lows))/(max(highs)-min(lows)) if max(highs)>min(lows) else None
    return {"code":canonical_code(code),"as_of":TARGET,"close":round(close,6),"return_1d_pct":round(ret(closes,1),6),"return_5d_pct":round(ret(closes,5),6),"return_10d_pct":round(ret(closes,10),6),"return_20d_pct":round(ret(closes,20),6),"ma5":round(ma5,6),"ma10":round(ma10,6),"ma20":round(ma20,6),"bias_ma5_pct":round((close/ma5-1)*100,6) if ma5 else None,"bias_ma20_pct":round((close/ma20-1)*100,6) if ma20 else None,"volume_ratio":round(vr,6),"realized_vol20_ann_pct":round(math.sqrt(variance)*math.sqrt(252),6),"position_in_20d_range":round(pos,6) if pos is not None else None,"source":"TencentFetcher:qfq"}


def main():
    p=argparse.ArgumentParser();
    for name in ("db","universe","integrity","r5","r6","r7","contract","output"): p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args(); u=load_json(a.universe); integ=load_json(a.integrity); r5=load_json(a.r5); r6=load_json(a.r6); r7=load_json(a.r7); contract=load_json(a.contract)
    members=[canonical_code(x["code"]) for x in u["members"]]; by={canonical_code(x["code"]):x for x in integ["coverage"]}
    assert len(members)==660 and len(set(members))==660 and integ["denominator"]==660 and integ["isolated"]==253 and contract["source_denominator"]==660
    original={c for c in members if by[c].get("status")=="passed_21_observed_daily_bars"}; assert len(original)==407
    geo={canonical_code(x["code"]) for x in r5["rows"] if x["classification"]=="RECOVERABLE_BY_TENCENT_QFQ_FALLBACK"}; assert len(geo)==114
    dis={canonical_code(x["code"]) for x in r6["rows"] if x["classification"] in ("RAW_PRICE_AGREEMENT_TIGHT","RAW_PRICE_AGREEMENT_LOOSE")}; conflict={canonical_code(x["code"]) for x in r6["rows"] if x["classification"]=="RAW_PRICE_CONFLICT"}; assert len(dis)==113 and len(conflict)==19
    missing={canonical_code(x["code"]) for x in r7["rows"] if x["classification"]=="RECOVERABLE_YAHOO_HISTORY_GAP"}; stale={canonical_code(x["code"]) for x in r7["rows"] if x["classification"]=="STALE_OR_SUSPENDED_BEFORE_TARGET"}; assert len(missing)==4 and len(stale)==3
    recovered=geo|dis|missing; retained=conflict|stale
    assert len(recovered)==231 and len(retained)==22 and original.isdisjoint(recovered|retained) and original|recovered|retained==set(members)
    rows=[]; errors=[]; lock=Lock()
    for code in sorted(original):
        try: f=technical_features(a.db,code,TARGET); rows.append({"code":code,"route":"ORIGINAL_ACCEPTED","features":f,"feature_sha256":canonical_hash(f)})
        except Exception as e: errors.append({"code":code,"route":"ORIGINAL_ACCEPTED","error":type(e).__name__+":"+str(e)[:120]})
    def one(code):
        rec={"code":code,"route":"TENCENT_QFQ_RECOVERY"}
        try:
            sha, bars=qfq_rows(code); f=fallback_features(code,bars); rec.update(response_sha256=sha,features=f,feature_sha256=canonical_hash(f))
        except Exception as e: rec["error"]=type(e).__name__+":"+str(e)[:160]
        with lock:
            (errors if "error" in rec else rows).append(rec)
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(one,sorted(recovered)))
    rows.sort(key=lambda x:x["code"]); errors.sort(key=lambda x:x["code"])
    ready={r["code"] for r in rows}; assert len(ready)==638 and not errors and ready==original|recovered
    retained_rows=[]
    for code in sorted(retained): retained_rows.append({"code":code,"reason":"RAW_SOURCE_CONFLICT" if code in conflict else "STALE_OR_SUSPENDED"})
    feature_projection=[{"code":r["code"],"route":r["route"],"feature_sha256":r["feature_sha256"]} for r in rows]
    report={"schema_version":1,"run_id":"TRI-DSA-DAT-20260914-006-COUNTERFACTUAL-R8","as_of":TARGET,"denominator":660,"original_ready":407,"recovered_ready":231,"total_feature_ready":638,"retained_isolated":22,"coverage_pct":round(638/660*100,6),"recovery_breakdown":{"geometry":114,"adjustment_or_rounding":113,"yahoo_history_gap":4},"retained_breakdown":{"raw_source_conflict":19,"stale_or_suspended":3},"feature_input_sha256":canonical_hash(feature_projection),"rows":rows,"retained":retained_rows,"errors":errors,"model_http_requests":0,"paid_data_used":False,"outcome_data_read":False,"frozen_predictions_rewritten":False,"run005_a0_a3_unchanged":True,"contract_sha256":hashlib.sha256(a.contract.read_bytes()).hexdigest()}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)); print("RUN006_RECOVERY_COUNTERFACTUAL",json.dumps({k:report[k] for k in ("denominator","original_ready","recovered_ready","total_feature_ready","retained_isolated","coverage_pct","feature_input_sha256")},ensure_ascii=False),flush=True)

if __name__=="__main__": main()
