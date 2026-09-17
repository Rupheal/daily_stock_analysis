"""Fresh model-free preflight for Run058A O micro-batch 00001/00002.

Uses the frozen original DSA checkout for market-data materialization, Tencent as
an independent public history source, and the accepted O native input contract.
No model credential is accepted or used here.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import pandas as pd

CODES=("00001","00002")

def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def canonical_sha(value) -> str:
    return sha_bytes(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode())

def write_json(path: Path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+"\n")

def validate_native_rows(rows, target, minimum=21):
    out=[]
    for raw in rows:
        r=dict(raw); r["date"]=str(r["date"])[:10]
        if r["date"]>target: raise ValueError("FUTURE_BAR_IN_FRESH_PREFLIGHT")
        for k in ("open","high","low","close","volume"):
            if isinstance(r.get(k),bool): raise ValueError("INVALID_MARKET_NUMBER")
            r[k]=float(r[k])
            if not math.isfinite(r[k]): raise ValueError("NONFINITE_MARKET_NUMBER")
        if not 0<r["low"]<=min(r["open"],r["close"])<=max(r["open"],r["close"])<=r["high"]:
            raise ValueError("INVALID_BAR_GEOMETRY")
        if r["volume"]<0: raise ValueError("NEGATIVE_VOLUME")
        out.append(r)
    dates=[x["date"] for x in out]
    if dates!=sorted(set(dates)): raise ValueError("DUPLICATE_OR_UNSORTED_HISTORY")
    if len(out)<minimum: raise ValueError("LESS_THAN_21_BARS")
    if dates[-1]!=target: raise ValueError("TARGET_MISSING")
    return out

def pit_members(universe, target, decision_session):
    if not universe.get("full_union_verified"): raise ValueError("PIT_UNIVERSE_NOT_VERIFIED")
    if universe.get("effective_session")!=target: raise ValueError("PIT_EFFECTIVE_SESSION_MISMATCH")
    if universe.get("member_count")!=660 or len(universe.get("members",[]))!=660:
        raise ValueError("PIT_DENOMINATOR_MISMATCH")
    observed=universe.get("observed_at_utc")
    if observed:
        obs=datetime.fromisoformat(observed.replace("Z","+00:00"))
        cutoff=datetime.fromisoformat(target+"T16:10:00+08:00").astimezone(timezone.utc)
        if obs>cutoff: raise ValueError("PIT_UNIVERSE_FUTURE_AVAILABLE")
    by={m["code"]:m for m in universe["members"]}
    result={}
    for code in CODES:
        m=by.get(code)
        if not m or not m.get("channels"): raise ValueError("PIT_MEMBER_MISSING_"+code)
        result[code]=m
    return result

def native_command(checkout: Path, target: str):
    wrapper=Path(__file__).resolve().parent/"run_original_with_target_adapter.py"
    return [sys.executable,str(wrapper),"--checkout",str(checkout),"--target",target,"--",
            "--stocks",",".join("hk"+c for c in CODES),"--dry-run","--no-notify",
            "--no-market-review","--force-run","--workers","2"]

def read_native(database: Path, code: str, target: str):
    cols=("date","open","high","low","close","volume","amount","data_source")
    with sqlite3.connect("file:"+str(database)+"?mode=ro",uri=True) as con:
        existing={r[1] for r in con.execute("PRAGMA table_info(stock_daily)")}
        selected=[x for x in cols if x in existing]
        if not set(("date","open","high","low","close","volume"))<=set(selected):
            raise ValueError("MARKET_HISTORY_SCHEMA_MISSING")
        raw=con.execute("SELECT "+",".join(selected)+" FROM stock_daily WHERE code=? COLLATE NOCASE AND substr(date,1,10)<=? ORDER BY date",
                        ("hk"+code,target)).fetchall()
    rows=[]
    for values in raw:
        row={k:(None if isinstance(v,float) and not math.isfinite(v) else v) for k,v in zip(selected,values)}
        rows.append(row)
    return validate_native_rows(rows,target)

def tencent_history(code: str, target: str, rawdir: Path):
    from audit_dual_history_cache import tencent_rows
    url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
    resp=requests.get(url,params={"param":f"hk{code},day,,,180,qfq"},timeout=(8,20))
    resp.raise_for_status(); raw=resp.content
    rawdir.mkdir(parents=True,exist_ok=True); (rawdir/(code+".json")).write_bytes(raw)
    payload=json.loads(raw)
    rows=tencent_rows(payload,code,target)
    return rows,{"url":resp.url,"retrieved_at":datetime.now(timezone.utc).isoformat(),"sha256":sha_bytes(raw)}

def price_conflicts(primary, independent, limit=20):
    by={str(r["date"])[:10]:r for r in independent.to_dict("records")}
    out=[]
    for left in primary.to_dict("records"):
        day=str(left["date"])[:10]; right=by.get(day)
        if not right: continue
        for k in ("open","high","low","close"):
            a=float(left[k]); b=float(right[k]); d=abs(a-b)
            if d>0.005+1e-9:
                out.append({"date":day,"field":k,"tencent_qfq":a,"native":b,"abs_diff":d,
                            "ratio":(a/b if b else None)})
                if len(out)>=limit:return out
    return out

def build_preflight(code, member, native, tencent, source, universe_raw, target, out):
    from data_provider.tencent_fetcher import TencentFetcher
    from prepare_xiaomi_acceptance import compare_prices
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts
    fetcher=TencentFetcher()
    tdf=pd.DataFrame(tencent)
    tdf=fetcher._calculate_indicators(fetcher._clean_data(fetcher._normalize_data(tdf,"HK"+code)))
    tdf["date"]=pd.to_datetime(tdf["date"]).dt.strftime("%Y-%m-%d")
    native_dates={r["date"] for r in native}
    tdf=tdf[tdf["date"].isin(native_dates)].sort_values("date")
    if set(tdf["date"])!=native_dates: raise ValueError("TENCENT_NATIVE_WINDOW_MISMATCH")
    ndf=pd.DataFrame(native).sort_values("date")
    def diag_row(frame):
        r=frame.iloc[-1]
        return {"date":str(r["date"])[:10],**{k:float(r[k]) for k in ("open","high","low","close","volume")}}
    diag={"code":code,"target":target,"native_count":len(native),"tencent_count":len(tencent),
          "conflicts":price_conflicts(tdf,ndf),
          "native_target":diag_row(ndf),"tencent_target":diag_row(tdf)}
    write_json(out/"PRICE_DIAGNOSTIC.json",diag)
    try:
        overlap,reconciliation=compare_prices(tdf,ndf,target,True,minimum_overlap=len(native))
    except Exception as exc:
        diag["compare_error"]=type(exc).__name__+":"+str(exc)
        write_json(out/"PRICE_DIAGNOSTIC.json",diag)
        print("RUN058A0_PRICE_DIAGNOSTIC "+json.dumps(diag,ensure_ascii=False,default=str),flush=True)
        raise
    today,yesterday=tdf.iloc[-1].to_dict(),tdf.iloc[-2].to_dict()
    for row in (today,yesterday):
        if row.get("amount") is not None:
            try:
                if not math.isfinite(float(row["amount"])): row["amount"]=None
            except Exception:
                row["amount"]=None
    context={"today":today,"yesterday":yesterday,
             "volume_change_ratio":round(float(today["volume"])/float(yesterday["volume"]),2) if float(yesterday["volume"]) else None}
    validate_daily_context(context,target)
    prepared=datetime.now(timezone.utc).isoformat()
    native_sha=canonical_sha(native)
    preflight={
      "passed":True,"symbol":"HK"+code,"stock_name":member.get("official_name") or member.get("english_name") or code,
      "prices_passed":True,"prepared_at":prepared,"target":target,
      "today":today,"yesterday":yesterday,"facts":daily_consistency_facts(context),
      "price_reconciliation":reconciliation,"overlap":overlap,
      "validated_native_history":native,
      "native_history_window":{"first":native[0]["date"],"last":target,"count":len(native),
        "scope":"Fresh original-native window independently compared with Tencent qfq; every stored bar geometry checked.",
        "ma60_supported":len(native)>=60},
      "component_status":{"prices":"passed","news":"passed_limited_coverage"},
      "news_count":0,"allowed_news_urls":[],"company_news_evidence":[],
      "execution_contract":{"version":"O_GATE_A_EXECUTION_CONTRACT_v2","realtime_quote_available":False,
        "target_session":target,"session_fact_anchor_required":True},
      "hk_report_contract":{"required_risk_ids":["FRESH_NEWS_NOT_REVIEWED"]},
      "risk_review_complete":False,
      "limitation":"Fresh price/history gate only. No fresh news search was admitted; zero events does not mean no issuer risk and cannot promote a signal.",
      "sources":{"universe_sha256":sha_bytes(universe_raw),"pit_effective_session":target,
        "native_history_sha256":native_sha,"tencent":source}
    }
    write_json(out/"preflight.json",preflight)
    return preflight

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkout",type=Path,required=True)
    ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--scope",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); scope=json.loads(a.scope.read_text()); a.out.mkdir(parents=True,exist_ok=False)
    if tuple(scope["codes"])!=CODES or scope["resource_boundary"]["model_http_requests"]!=0:
        raise ValueError("SCOPE_BOUNDARY_INVALID")
    target=scope["target_session"]; decision=scope["decision_session"]
    if target!="2026-09-17" or decision!="2026-09-18": raise ValueError("FROZEN_SESSION_INVALID")
    from o_target_session_contract import resolve_target_session
    now=datetime.now(timezone.utc)
    if resolve_target_session(now).target_session.isoformat()!=target: raise ValueError("CURRENT_TARGET_SESSION_MISMATCH")
    if now.astimezone(ZoneInfo("Asia/Hong_Kong")).date().isoformat()!=decision: raise ValueError("DECISION_SESSION_MISMATCH")
    universe_raw=a.universe.read_bytes(); universe=json.loads(universe_raw); members=pit_members(universe,target,decision)
    checkout=a.checkout.resolve()
    actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=checkout,text=True).strip()
    if actual!=scope["frozen_upstream"]: raise ValueError("NATIVE_CHECKOUT_COMMIT_MISMATCH")
    if subprocess.check_output(["git","diff","--name-only","HEAD"],cwd=checkout,text=True).strip():
        raise ValueError("NATIVE_CHECKOUT_DIRTY")
    database=a.out/"native-data.db"
    env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    env.update(ENV_FILE="/dev/null",DATABASE_PATH=str(database),BACKTEST_ENABLED="false",
               NEWS_INTEL_AUTO_FETCH_ENABLED="false",PYTHONUNBUFFERED="1")
    if any(k for k in env if "DEEPSEEK" in k.upper() and ("KEY" in k.upper() or "TOKEN" in k.upper())):
        raise ValueError("MODEL_CREDENTIAL_PRESENT")
    cmd=native_command(checkout,target)
    with (a.out/"native.log").open("w") as log:
        proc=subprocess.run(cmd,cwd=checkout,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    if proc.returncode!=0: raise ValueError("FRESH_NATIVE_DATA_COMMAND_FAILED")
    rows={code:read_native(database,code,target) for code in CODES}
    rawdir=a.out/"tencent-raw"; preflights={}; member_receipts=[]
    for code in CODES:
        trows,source=tencent_history(code,target,rawdir)
        pfdir=a.out/("HK"+code)
        pf=build_preflight(code,members[code],rows[code],trows,source,universe_raw,target,pfdir)
        pbytes=(pfdir/"preflight.json").read_bytes()
        member_receipts.append({
          "code":code,"status":"PASS_FRESH_PREFLIGHT","native_sessions":len(rows[code]),
          "native_first":rows[code][0]["date"],"native_last":rows[code][-1]["date"],
          "native_history_sha256":pf["sources"]["native_history_sha256"],
          "tencent_raw_sha256":source["sha256"],"preflight_sha256":sha_bytes(pbytes),
          "pit_channels":members[code]["channels"],"model_http_requests":0
        })
        preflights[code]=pf
    result={
      "schema_version":1,"run_id":scope["run_id"],"state":"PASS_FRESH_PREFLIGHT",
      "parent_controller_commit":scope["parent_controller_commit"],"micro_batch_id":scope["micro_batch_id"],
      "target_session":target,"decision_session":decision,
      "pit":{"universe_sha256":sha_bytes(universe_raw),"effective_session":universe["effective_session"],
        "observed_at_utc":universe.get("observed_at_utc"),"denominator":universe["member_count"],"full_union_verified":universe["full_union_verified"]},
      "members":member_receipts,
      "fresh_history_all_pass":all(x["status"]=="PASS_FRESH_PREFLIGHT" and x["native_sessions"]>=21 and x["native_last"]==target for x in member_receipts),
      "resource_accounting":{"model_http_requests":0,"paid_data_calls":0,"deepseek_cost_cny":"0","automatic_recharge":False},
      "safety":{"provider_send_authorized":False,"real_orders":0,"simulation_ledger_writes":0,"schedule_changes":0,"main_merge":0},
      "native_db_sha256":sha_bytes(database.read_bytes()),
      "native_log_sha256":sha_bytes((a.out/"native.log").read_bytes()),
      "next":"Run058A may be created only from these exact preflight hashes; it must recheck Drive claim and balance before each provider send."
    }
    write_json(a.out/"RUN058A0_FRESH_PREFLIGHT_RESULT.json",result)
    print("RUN058A0_FRESH_PREFLIGHT "+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
