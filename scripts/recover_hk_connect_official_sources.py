"""Run058U bounded official-source recovery for HK Connect universe.
Official SSE/SZSE/HKEX only. No provider/model/Drive/trading calls.
Retries transport errors a bounded number of times and preserves raw bytes + hashes.
"""
from __future__ import annotations
import argparse, hashlib, io, json, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from openpyxl import load_workbook

SOURCES={
 "sse-list.json":{
   "url":"https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L&isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&keyword=",
   "referer":"https://www.sse.com.cn/services/hkexsc/disclo/eligible/"},
 "szse-list.json":{
   "url":"https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1",
   "referer":"https://www.szse.cn/szhk/hkbussiness/underlylist/index.html"},
 "szse-list.xlsx":{
   "url":"https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1",
   "referer":"https://www.szse.cn/szhk/hkbussiness/underlylist/index.html"},
 "hkex-securities.xlsx":{
   "url":"https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx",
   "referer":"https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en"},
}

def validate(name,data,session):
    if len(data)>5_000_000: raise ValueError("SOURCE_TOO_LARGE")
    if name=="sse-list.json":
        d=json.loads(data); rows=d.get("result") or []
        if not rows or {x.get("UPDATE_DATE") for x in rows}!={session}: raise ValueError("SSE_SESSION_UNVERIFIED")
        if len(rows)!=int(d["pageHelp"]["total"]) or int(d["pageHelp"]["pageCount"])!=1: raise ValueError("SSE_PAGINATION_INCOMPLETE")
    elif name=="szse-list.json":
        d=json.loads(data)
        if not isinstance(d,list) or not d or "metadata" not in d[0]: raise ValueError("SZSE_JSON_SCHEMA_CHANGED")
        meta=d[0]["metadata"]
        if str(meta.get("subname"))!=session: raise ValueError("SZSE_JSON_SESSION_UNVERIFIED")
        if int(meta.get("recordcount",0))<=0: raise ValueError("SZSE_JSON_EMPTY")
    else:
        wb=load_workbook(io.BytesIO(data),read_only=True,data_only=True); sh=wb.active; sh.reset_dimensions(); rows=list(sh.values); wb.close()
        if name=="szse-list.xlsx":
            if not rows or tuple(rows[0][:3])!=("证券代码","中文简称","英文简称"): raise ValueError("SZSE_XLSX_HEADER_CHANGED")
        else:
            expected="Updated as at "+datetime.fromisoformat(session).strftime("%d/%m/%Y")
            if len(rows)<4 or rows[1][0]!=expected: raise ValueError("HKEX_SESSION_UNVERIFIED")
            if tuple(rows[2][:5])!=("Stock Code","Name of Securities","Category","Sub-Category","Board Lot"): raise ValueError("HKEX_HEADER_CHANGED")
    return True

def fetch_one(name,spec,out,session,attempts):
    row={"file":name,"url":spec["url"],"attempts":[]}
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
             "Referer":spec["referer"],"Accept":"*/*","Connection":"close"}
    for i in range(1,attempts+1):
        a={"attempt":i,"started_at":datetime.now(timezone.utc).isoformat()}
        try:
            with requests.Session() as s:
                r=s.get(spec["url"],headers=headers,timeout=(10,30),allow_redirects=True)
                r.raise_for_status(); data=r.content
            validate(name,data,session)
            (out/name).write_bytes(data)
            a.update(status="received",http_status=r.status_code,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            a["completed_at"]=datetime.now(timezone.utc).isoformat()\n            row["attempts"].append(a); row.update(status="received",bytes=len(data),sha256=a["sha256"],successful_attempt=i,started_at=row["attempts"][0]["started_at"],completed_at=a["completed_at"])\n            return row
        except Exception as exc:
            a.update(status="failed",error=type(exc).__name__+":"+str(exc)[:180],completed_at=datetime.now(timezone.utc).isoformat()); row["attempts"].append(a)
            if i<attempts: time.sleep(i)
    row["status"]="failed"; row["error"]=row["attempts"][-1]["error"]; row["started_at"]=row["attempts"][0]["started_at"]; row["completed_at"]=row["attempts"][-1]["completed_at"]\n    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--session",required=True);ap.add_argument("--out",type=Path,required=True);ap.add_argument("--attempts",type=int,default=3)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=False)
    rows=[fetch_one(n,s,a.out,a.session,a.attempts) for n,s in SOURCES.items()]
    complete=all(x["status"]=="received" for x in rows)
    receipt={"schema_version":1,"run_id":"TRI-DSA-O-SOURCE-RECOVERY-20260918-058U",
             "session":a.session,"complete_official_bundle":complete,"sources":rows,
             "model_http_requests":0,"provider_credentials_used":False,"drive_writes":0,
             "paid_data_calls":0,"DeepSeek_API_cost_cny":0,"real_orders":0}
    (a.out/"source-recovery.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(receipt,ensure_ascii=False))
    if not complete: raise SystemExit(2)
if __name__=="__main__": main()
