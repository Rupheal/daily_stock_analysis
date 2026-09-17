#!/usr/bin/env python3
"""Current-session U45 independent daily integrity adapter.

Preserves the accepted Run004 integrity semantics while removing only the old
retained-database hash pin.  The output contract is the same U-integrity shape
consumed by the accepted Run004 v2 ranking runner.  Free public data only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hk_batch_integrity import canonical, native_rows, validate_rows, tencent_rows, compare_history


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_report(db, universe, target, output):
    universe_obj=json.loads(Path(universe).read_text(encoding='utf-8'))
    codes=[canonical(x['code']) for x in universe_obj['members']]
    if len(codes)!=45 or universe_obj.get('member_count')!=45 or len(set(codes))!=45:
        raise ValueError('U45_UNIVERSE_CONTRACT_MISMATCH')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    lock=Lock();rows=[]

    def one(code):
        r={'code':code,'status':'isolated'}
        try:
            native=native_rows(Path(db),code);validate_rows(native,target)
            native_source=str(native[-1].get('data_source') or '')
            if 'Tencent' in native_source:
                import yfinance as yf
                ticker=code[2:].lstrip('0').zfill(4)+'.HK'
                frame=yf.Ticker(ticker).history(period='3mo',auto_adjust=True,actions=True,timeout=20)
                independent=[{'date':str(idx)[:10],**{k:float(row[k.title()]) for k in ('open','high','low','close','volume')}} for idx,row in frame.iterrows()]
                provider='YfinanceFetcher';adjustment='auto_adjust=True'
                payload=json.dumps({'provider':provider,'ticker':ticker,'retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':independent},ensure_ascii=False,default=str).encode()
                (out/(code+'-yahoo.json')).write_bytes(payload)
                source_sha=hashlib.sha256(payload).hexdigest()
            else:
                url='https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?'+urlencode({'param':code.lower()+',day,,,180,qfq'})
                with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:
                    raw=response.read(2_000_000)
                payload=json.loads(raw);independent,adjustment=tencent_rows(payload,code);provider='TencentFetcher'
                (out/(code+'-tencent.json')).write_bytes(raw);source_sha=hashlib.sha256(raw).hexdigest()
            independent=[x for x in independent if x['date']<=target]
            audit=compare_history(native,independent,target,provider)
            r.update(audit=audit,adjustment=adjustment,native_source=native_source,independent_provider=provider,independent_source_sha256=source_sha)
            if audit['passed']:r['status']='passed_21_observed_daily_bars'
            else:r['reason']='independent_daily_disagreement'
        except Exception as exc:
            r['reason']=type(exc).__name__+':'+str(exc)[:160]
            if hasattr(exc,'public_row'):r['invalid_bar']=exc.public_row
        with lock: rows.append(r)

    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,codes))
    rows.sort(key=lambda x:x['code'])
    isolated=[x for x in rows if x['status']=='isolated']
    reasons={}
    for x in isolated:reasons[x['reason']]=reasons.get(x['reason'],0)+1
    report={'schema':'RUN050_U45_INTEGRITY_v1','track':'U','target':target,'denominator':45,
            'passed':45-len(isolated),'isolated':len(isolated),'reasons':reasons,
            'database_sha256':file_sha(db),'coverage':rows,'model_http_requests':0,'model_fees_cny':'0',
            'scope':'free independent public last-21-observed-daily OHLCV comparison; versioned current-session adapter of accepted Run004 integrity semantics'}
    (out/'U-integrity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--universe',required=True);p.add_argument('--target',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=build_report(a.db,a.universe,a.target,a.output)
    print(json.dumps({k:v for k,v in r.items() if k!='coverage'},ensure_ascii=False))

if __name__=='__main__':main()
