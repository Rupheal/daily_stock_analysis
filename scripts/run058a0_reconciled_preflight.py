"""Run058A0 corporate-action-aware fresh preflight.

Reuses the accepted Run006 recovery rule:
strict adjusted agreement if available; otherwise verify Yahoo raw vs Tencent raw,
independently verify Sina raw vs Tencent raw, bind an official HKEX corporate action,
and freeze Tencent qfq as the accepted input. No model or private-store credentials.
"""
from __future__ import annotations
import argparse, hashlib, io, json, math, os, sqlite3, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import yfinance as yf
from pypdf import PdfReader

CODES=("00001","00002")

def sha(raw): return hashlib.sha256(raw).hexdigest()
def canon(v): return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode())
def write(p,v): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False,default=str)+"\n")

def finite_rows(rows,target,minimum=21):
    out=[]
    for x in rows:
        r=dict(x);r["date"]=str(r["date"])[:10]
        if r["date"]>target: continue
        for k in ("open","high","low","close","volume"):
            r[k]=float(r[k])
            if not math.isfinite(r[k]): raise ValueError("NONFINITE_"+k.upper())
        if not 0<r["low"]<=min(r["open"],r["close"])<=max(r["open"],r["close"])<=r["high"]: raise ValueError("INVALID_BAR_GEOMETRY")
        if r["volume"]<0: raise ValueError("NEGATIVE_VOLUME")
        out.append(r)
    out=out[-minimum:]
    if len(out)!=minimum or out[-1]["date"]!=target or [x["date"] for x in out]!=sorted({x["date"] for x in out}):
        raise ValueError("FRESH_WINDOW_INCOMPLETE")
    return out

def read_native(db,code,target):
    with sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True) as con:
        cols={r[1] for r in con.execute("PRAGMA table_info(stock_daily)")}
        want=[k for k in ("date","open","high","low","close","volume") if k in cols]
        rows=con.execute("SELECT "+",".join(want)+" FROM stock_daily WHERE code=? COLLATE NOCASE AND substr(date,1,10)<=? ORDER BY date",
                         ("hk"+code,target)).fetchall()
    return finite_rows([{k:v for k,v in zip(want,row)} for row in rows],target)

def tencent(code,target,kind,out):
    if kind=="qfq":
        url="https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get";params={"param":f"hk{code},day,,,180,qfq"}
    else:
        url="https://web.ifzq.gtimg.cn/appstock/app/kline/kline";params={"param":f"hk{code},day,,,180"}
    r=requests.get(url,params=params,timeout=(8,20));r.raise_for_status();raw=r.content
    out.write_bytes(raw); obj=r.json()["data"]["hk"+code]
    arr=(obj.get("qfqday") or obj.get("day") or []) if kind=="qfq" else (obj.get("day") or [])
    rows=[dict(zip(("date","open","close","high","low","volume"),x[:6])) for x in arr]
    return finite_rows(rows,target),{"url":r.url,"sha256":sha(raw),"retrieved_at":datetime.now(timezone.utc).isoformat()}

def yahoo_raw(code,target,out):
    end=datetime.fromisoformat(target)+timedelta(days=1);start=end-timedelta(days=70)
    f=yf.Ticker(f"{int(code):04d}.HK").history(start=start.date().isoformat(),end=end.date().isoformat(),
        auto_adjust=False,actions=True,repair=False,timeout=20)
    rows=[];actions=[]
    for idx,v in f.iterrows():
        day=str(idx)[:10]
        if day>target: continue
        z={"date":day,"open":float(v["Open"]),"high":float(v["High"]),"low":float(v["Low"]),
           "close":float(v["Close"]),"volume":float(v["Volume"])}
        rows.append(z)
        if float(v.get("Dividends",0) or 0)!=0 or float(v.get("Stock Splits",0) or 0)!=0:
            actions.append({"date":day,"dividends":float(v.get("Dividends",0) or 0),"stock_splits":float(v.get("Stock Splits",0) or 0)})
    rows=finite_rows(rows,target)
    payload={"provider":"Yahoo yfinance auto_adjust=False repair=False","rows":rows,"actions":actions}
    write(out,payload)
    return rows,actions,{"sha256":sha(out.read_bytes()),"source_locator":f"https://query1.finance.yahoo.com/v8/finance/chart/{int(code):04d}.HK"}

def sina_raw(code,target,out):
    from akshare.stock.cons import hk_js_decode,hk_sina_stock_hist_url
    from py_mini_racer import MiniRacer
    url=hk_sina_stock_hist_url.format(code);r=requests.get(url,timeout=(5,15));r.raise_for_status();raw=r.content;out.write_bytes(raw)
    ctx=MiniRacer();ctx.eval(hk_js_decode);decoded=ctx.call("d",r.text.split("=",1)[1].split(";",1)[0].replace('"',""))
    rows=[{"date":str(x["date"])[:10],**{k:float(x[k]) for k in ("open","high","low","close","volume")}} for x in decoded]
    return finite_rows(rows,target),{"url":url,"sha256":sha(raw),"retrieved_at":datetime.now(timezone.utc).isoformat()}

def official_action(item,out):
    r=requests.get(item["source_url"],timeout=(8,30));r.raise_for_status();raw=r.content;out.write_bytes(raw)
    text="\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
    required=[item["issuer"].split(" Limited")[0],item["dividend_hkd_per_share"],item["ex_dividend_date"].replace("-"," ")]
    # PDF renders the date in long English form; validate issuer/code/amount and ex-date components separately.
    if item["issuer"].split(" Limited")[0] not in text or item["dividend_hkd_per_share"] not in text:
        raise ValueError("OFFICIAL_ACTION_TEXT_MISMATCH")
    y,m,d=item["ex_dividend_date"].split("-")
    months={"01":"January","02":"February","03":"March","04":"April","05":"May","06":"June","07":"July","08":"August","09":"September","10":"October","11":"November","12":"December"}
    if f"{int(d):02d} {months[m]} {y}" not in text and f"{int(d)} {months[m]} {y}" not in text:
        raise ValueError("OFFICIAL_EXDATE_MISMATCH")
    return {"source_url":item["source_url"],"pdf_sha256":sha(raw),"ex_dividend_date":item["ex_dividend_date"],
            "dividend_hkd_per_share":item["dividend_hkd_per_share"],"primary_source_verified":True}

def make_context(rows,code):
    from data_provider.tencent_fetcher import TencentFetcher
    f=TencentFetcher();df=pd.DataFrame(rows);df["amount"]=None;df["pct_chg"]=None;df=f._calculate_indicators(f._clean_data(f._normalize_data(df,"HK"+code)))
    df["date"]=pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    today=df.iloc[-1].to_dict();yesterday=df.iloc[-2].to_dict()
    for z in (today,yesterday):
        for k,v in list(z.items()):
            if isinstance(v,float) and not math.isfinite(v): z[k]=None
    return today,yesterday

def main():
    ap=argparse.ArgumentParser()
    for k in ("checkout","universe","scope","actions","out"):ap.add_argument("--"+k,type=Path,required=True)
    a=ap.parse_args();scope=json.loads(a.scope.read_text());actions=json.loads(a.actions.read_text())["items"];a.out.mkdir(parents=True,exist_ok=False)
    target=scope["target_session"];now=datetime.now(timezone.utc)
    from o_target_session_contract import resolve_target_session
    if resolve_target_session(now).target_session.isoformat()!=target or now.astimezone(ZoneInfo("Asia/Hong_Kong")).date().isoformat()!="2026-09-18":
        raise ValueError("TARGET_OR_DECISION_SESSION_MISMATCH")
    universe_raw=a.universe.read_bytes();u=json.loads(universe_raw)
    if not (u["full_union_verified"] and u["effective_session"]==target and u["member_count"]==660):raise ValueError("PIT_UNIVERSE_MISMATCH")
    members={x["code"]:x for x in u["members"]}
    if not set(CODES)<=set(members):raise ValueError("PIT_MEMBERS_MISSING")
    checkout=a.checkout.resolve()
    if subprocess.check_output(["git","rev-parse","HEAD"],cwd=checkout,text=True).strip()!=scope["frozen_upstream"]:raise ValueError("UPSTREAM_MISMATCH")
    db=a.out/"native.db";env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    env.update(ENV_FILE="/dev/null",DATABASE_PATH=str(db),BACKTEST_ENABLED="false",NEWS_INTEL_AUTO_FETCH_ENABLED="false")
    wrapper=Path(__file__).resolve().parent/"run_original_with_target_adapter.py"
    cmd=[sys.executable,str(wrapper),"--checkout",str(checkout),"--target",target,"--","--stocks",",".join("hk"+x for x in CODES),"--dry-run","--no-notify","--no-market-review","--force-run","--workers","2"]
    with (a.out/"native.log").open("w") as log:
        q=subprocess.run(cmd,cwd=checkout,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    if q.returncode:raise ValueError("ORIGINAL_NATIVE_DATA_FAILED")
    from prepare_xiaomi_acceptance import compare_prices
    from apply_run006_current_recovery import raw_agreement
    from reconcile_hk_third_source import whole_window_agrees
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts
    receipts=[];all_pass=True
    for code in CODES:
        d=a.out/code;d.mkdir()
        native=read_native(db,code,target)
        tq,tqsrc=tencent(code,target,"qfq",d/"tencent-qfq.json")
        tr,trsrc=tencent(code,target,"raw",d/"tencent-raw.json")
        yr,yacts,ysrc=yahoo_raw(code,target,d/"yahoo-raw.json")
        sr,ssrc=sina_raw(code,target,d/"sina-raw.js")
        official=official_action(actions[code],d/"hkex-action.pdf")
        from data_provider.tencent_fetcher import TencentFetcher
        f=TencentFetcher()
        qdf=pd.DataFrame(tq);qdf["amount"]=None;qdf["pct_chg"]=None
        qdf=f._calculate_indicators(f._clean_data(f._normalize_data(pd.DataFrame(tq),"HK"+code)));qdf["date"]=pd.to_datetime(qdf["date"]).dt.strftime("%Y-%m-%d")
        ndf=pd.DataFrame(native)
        strict=True;strict_error=None;recon=None
        try:
            _,recon=compare_prices(qdf,ndf,target,True,minimum_overlap=21)
        except Exception as exc:
            strict=False;strict_error=type(exc).__name__+":"+str(exc)
        raw_yt=raw_agreement(yr,tr,target);raw_st=whole_window_agrees(sr,tr,target)
        action_in_window=official["ex_dividend_date"]>=native[0]["date"] and official["ex_dividend_date"]<=target
        fallback=(not strict and raw_yt["class"] in ("RAW_PRICE_AGREEMENT_TIGHT","RAW_PRICE_AGREEMENT_LOOSE")
                  and raw_yt["exact_volume_agreement"] and raw_st.get("accepted") and action_in_window)
        accepted=native if strict else tq if fallback else None
        source="native-original" if strict else "Tencent:qfq+Yahoo_raw+Sina_raw+HKEX_action" if fallback else None
        status="PASS_ADJUSTED_STRICT" if strict else "PASS_RUN006_RAW_FALLBACK" if fallback else "RAW_GATE_BLOCK"
        if accepted is None: all_pass=False
        if accepted is not None:
            today,yesterday=make_context(accepted,code)
            context={"today":today,"yesterday":yesterday,"volume_change_ratio":round(float(today["volume"])/float(yesterday["volume"]),2) if float(yesterday["volume"]) else None}
            validate_daily_context(context,target)
            pf={"passed":True,"symbol":"HK"+code,"stock_name":members[code].get("official_name") or members[code].get("english_name") or code,
                "prices_passed":True,"prepared_at":datetime.now(timezone.utc).isoformat(),"target":target,
                "today":today,"yesterday":yesterday,"facts":daily_consistency_facts(context),
                "validated_native_history":accepted,
                "native_history_window":{"first":accepted[0]["date"],"last":accepted[-1]["date"],"count":len(accepted),
                  "scope":"Run006-compatible fresh accepted input; strict adjusted path or raw-arbitrated Tencent qfq fallback.","ma60_supported":False},
                "price_reconciliation":recon or {"status":"RUN006_RAW_FALLBACK","strict_adjusted_error":strict_error,
                  "yahoo_tencent_raw":raw_yt,"sina_tencent_raw":raw_st,"official_action":official},
                "component_status":{"prices":"passed","news":"passed_limited_coverage"},
                "news_count":0,"allowed_news_urls":[],"company_news_evidence":[],
                "execution_contract":{"version":"O_GATE_A_EXECUTION_CONTRACT_v2","realtime_quote_available":False,"target_session":target,"session_fact_anchor_required":True},
                "hk_report_contract":{"required_risk_ids":["FRESH_NEWS_NOT_REVIEWED"]},"risk_review_complete":False,
                "limitation":"Fresh market input accepted; fresh news not reviewed. No signal promotion.",
                "accepted_input_source":source,
                "sources":{"universe_sha256":sha(universe_raw),"tencent_qfq":tqsrc,"tencent_raw":trsrc,"yahoo_raw":ysrc,"sina_raw":ssrc,"official_action":official}}
            write(d/"preflight.json",pf);pfsha=sha((d/"preflight.json").read_bytes())
        else: pfsha=None
        diag={"code":code,"status":status,"strict_adjusted_pass":strict,"strict_adjusted_error":strict_error,
              "native_window_sha256":canon(native),"tencent_qfq_sha256":canon(tq),"yahoo_tencent_raw":raw_yt,
              "sina_tencent_raw":raw_st,"yahoo_reported_actions":yacts,"official_action":official,
              "accepted_input_source":source,"preflight_sha256":pfsha}
        write(d/"RECONCILIATION.json",diag)
        receipts.append(diag)
    result={"schema_version":2,"run_id":scope["run_id"],"state":"PASS_FRESH_PREFLIGHT" if all_pass else "RAW_GATE_BLOCK",
      "target_session":target,"decision_session":"2026-09-18","micro_batch_id":"O57-MB-001",
      "pit":{"denominator":660,"effective_session":u["effective_session"],"universe_sha256":sha(universe_raw),"full_union_verified":u["full_union_verified"]},
      "members":receipts,"fresh_history_all_pass":all_pass,
      "resource_accounting":{"model_http_requests":0,"paid_data_calls":0,"deepseek_cost_cny":"0","automatic_recharge":False},
      "safety":{"provider_send_authorized":False,"real_orders":0,"simulation_ledger_writes":0,"schedule_changes":0,"main_merge":0}}
    write(a.out/"RUN058A0_FRESH_PREFLIGHT_RESULT.json",result)
    print("RUN058A0_RECONCILED "+json.dumps(result,ensure_ascii=False),flush=True)
    if not all_pass:raise SystemExit(2)

if __name__=="__main__":main()
