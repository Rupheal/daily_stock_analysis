#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
from freeze_hk_connect_universe import freeze

URLS={
 'sse-list.json':'https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L&isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&keyword=',
 'szse-list.json':'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1',
 'szse-list.xlsx':'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1',
 'hkex-securities.xlsx':'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx',
}
def build(session:str,u_universe:Path,out:Path):
    src=out/'sources';src.mkdir(parents=True,exist_ok=False);rows=[]
    for name,url in URLS.items():
        started=datetime.now(timezone.utc).isoformat()
        for attempt in range(3):
            try:
                h={'User-Agent':'Mozilla/5.0','Accept':'*/*','Referer':'https://www.sse.com.cn/'}
                if 'szse.cn' in url:h['Referer']='https://www.szse.cn/'
                if 'hkex.com.hk' in url:h['Referer']='https://www.hkex.com.hk/'
                resp=requests.get(url,headers=h,timeout=(10,30));resp.raise_for_status();raw=resp.content
                if not raw: raise RuntimeError('EMPTY_SOURCE')
                (src/name).write_bytes(raw)
                rows.append({'file':name,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'status':'received','bytes':len(raw)})
                break
            except Exception:
                if attempt==2: raise
                time.sleep(1+attempt)
    (src/'source-probe.json').write_text(json.dumps({'schema_version':1,'sources':rows},indent=2)+'\n')
    o,u=freeze(src,session,u_universe)
    (out/'O_UNIVERSE.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
    (out/'U_UNIVERSE.json').write_text(json.dumps(u,ensure_ascii=False,indent=2)+'\n')
    return {'target_session':session,'O_denominator':o['member_count'],'U_denominator':45,'U_buy_eligible':sum(bool(x.get('channels')) for x in u['members']),'model_calls':0,'paid_data_calls':0,'real_orders':0}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--session',required=True);ap.add_argument('--u-universe',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=False);r=build(a.session,a.u_universe,a.out);print(json.dumps(r))
if __name__=='__main__':main()
