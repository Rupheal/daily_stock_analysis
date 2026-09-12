"""Bounded free historical-price probe for the benchmark and Xiaomi; no LLM."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import yfinance as yf


def main():
    root=Path('probe/history');root.mkdir(parents=True,exist_ok=True)
    results=[]
    for symbol in ['^HSI','1810.HK']:
        result={'symbol':symbol,'requested_start':'2025-04-01','requested_end_exclusive':'2026-09-12',
                'retrieved_at':datetime.now(timezone.utc).isoformat(),'auto_adjust':False,'historical_pit_verified':False}
        try:
            frame=yf.Ticker(symbol).history(start='2025-04-01',end='2026-09-12',auto_adjust=False,actions=True,raise_errors=True,timeout=20)
            if frame.empty:raise ValueError('Empty historical response')
            frame=frame.reset_index();frame['Date']=frame['Date'].astype(str)
            rows=frame.to_dict('records')
            if any(str(r['Date'])[:10]>'2026-09-11' for r in rows):raise ValueError('Future historical bar')
            raw=frame.to_csv(index=False).encode();name=symbol.replace('^','')+'.csv';(root/name).write_bytes(raw)
            result.update(status='received',rows=len(rows),sha256=hashlib.sha256(raw).hexdigest(),first=rows[0],last=rows[-1])
            print('HISTORICAL_PRICES',json.dumps({'symbol':symbol,'rows':rows},default=str),flush=True)
        except Exception as exc:
            result.update(status='failed',error=type(exc).__name__+': '+str(exc))
        results.append(result)
    (root/'historical-price-probe.json').write_text(json.dumps(results,indent=2,default=str))
    print('HISTORICAL_PRICE_PROBE',json.dumps(results,default=str),flush=True)
    # Independent source evidence for the three invalid native OHLC bars.
    # Never rewrite the native O database or silently swap its inputs.
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    for code in ['hk00719','hk01318','hk06715']:
        url='https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?'+urlencode({'param':code+',day,,,60,qfq'})
        receipt={'code':code,'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:raw=response.read(2000000)
            (root/(code+'.json')).write_bytes(raw)
            data=json.loads(raw).get('data',{}).get(code,{})
            receipt.update(status='received',sha256=hashlib.sha256(raw).hexdigest(),
                           bars={k:v[-2:] for k,v in data.items() if k in ['day','qfqday','hfqday']})
        except Exception as exc:receipt.update(status='failed',error=str(exc))
        print('INDEPENDENT_O_PRICE_CHECK',json.dumps(receipt),flush=True)
        (root/(code+'-receipt.json')).write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
