#!/usr/bin/env python3
"""Fetch authoritative HK Connect universe source bytes for one production cycle."""
from __future__ import annotations
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests

URLS={
  'sse-list.json':'https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L&isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&keyword=',
  'szse-list.json':'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1',
  'szse-list.xlsx':'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1',
  'hkex-securities.xlsx':'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx',
}

def fetch(out:Path):
    out.mkdir(parents=True,exist_ok=False)
    base={'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/','Accept':'*/*'}
    rows=[]
    for name,url in URLS.items():
        started=datetime.now(timezone.utc).isoformat();last=None
        for attempt in range(3):
            try:
                h=dict(base)
                if 'szse.cn' in url:h['Referer']='https://www.szse.cn/'
                if 'hkex.com.hk' in url:h['Referer']='https://www.hkex.com.hk/'
                r=requests.get(url,headers=h,timeout=(10,30));r.raise_for_status()
                data=r.content
                if not data:raise RuntimeError('EMPTY_SOURCE')
                (out/name).write_bytes(data)
                rows.append({'file':name,'url':url,'sha256':hashlib.sha256(data).hexdigest(),
                  'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),
                  'status':'received','bytes':len(data)})
                break
            except Exception as exc:
                last=type(exc).__name__
                if attempt==2:raise
                time.sleep(1+attempt)
    manifest={'schema_version':1,'source_count':len(rows),'sources':rows,'model_http_requests':0,'real_orders':0}
    (out/'source-probe.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    r=fetch(a.out);print(json.dumps({'sources_received':r['source_count'],'files':[x['file'] for x in r['sources']]}))
if __name__=='__main__':main()
