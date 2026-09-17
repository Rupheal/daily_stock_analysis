"""Target only previous isolations. Preserve every old conflict and all660.

New prospective data repair: Sina raw OHLCV must agree with a whole21-session
raw series from one existing publisher, under the frozen Run006 tolerances.
No voting over isolated fields, no averaging, no synthetic dates or volumes.
Publisher independence is not proof of separate upstream exchange feeds.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import hashlib
import json
import requests
from audit_dual_history_cache import normalized
from apply_run006_current_recovery import raw_agreement


def whole_window_agrees(left, right, target):
    try:
        left = normalized([x for x in left if x['date'] <= target][-21:], target)
        right = normalized([x for x in right if x['date'] <= target][-21:], target)
        if [x['date'] for x in left] != [x['date'] for x in right]:
            return {'accepted': False, 'reason': 'SESSION_SETS_DIFFER'}
        result = raw_agreement(left, right, target)
        result['accepted'] = (result['class'] in ('RAW_PRICE_AGREEMENT_TIGHT','RAW_PRICE_AGREEMENT_LOOSE')
                              and result['exact_volume_agreement'])
        return result
    except (ValueError, KeyError, TypeError) as exc:
        return {'accepted': False, 'reason': type(exc).__name__}


def main():
    p = argparse.ArgumentParser()
    for k in ('prior','parent','out','scope'): p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();s=json.loads(a.scope.read_text());a.out.mkdir(parents=True,exist_ok=False)
    priorpath=a.prior/'CURRENT_RECOVERY.json';raw=priorpath.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==s['prior_sha256']
    prior=json.loads(raw); parent=json.loads(a.parent.read_text());target=prior['target']
    isolated=[r for r in prior['rows'] if r['route']=='ISOLATED']
    assert len(isolated)==s['progress_denominator']==62 and len(prior['inputs'])==598
    assert parent['target_session']==target==s['target_session']
    def one(old):
        from akshare.stock.cons import hk_js_decode, hk_sina_stock_hist_url
        from py_mini_racer import MiniRacer
        code=old['code'];d=a.out/code;d.mkdir();r={'code':code,'old_reasons':old['reasons'],
            'status':'ISOLATED','source_locator':hk_sina_stock_hist_url.format(code)}
        try:
            response=requests.get(r['source_locator'],timeout=(5,15));response.raise_for_status()
            raw=response.content
            if len(raw)>2000000: raise ValueError('RESPONSE_TOO_LARGE')
            (d/'sina-raw.js').write_bytes(raw);r.update(source_sha256=hashlib.sha256(raw).hexdigest(),
                retrieved_at=datetime.now(timezone.utc).isoformat(),adjustment='unadjusted',volume_unit='shares')
            ctx=MiniRacer();ctx.eval(hk_js_decode)
            decoded=ctx.call('d',response.text.split('=',1)[1].split(';',1)[0].replace('"',''))
            rows=[{'date':str(x['date'])[:10],**{k:float(x[k]) for k in ('open','high','low','close','volume')}} for x in decoded]
            (d/'sina-normalized.json').write_text(json.dumps(rows,allow_nan=False))
            sr=normalized([x for x in rows if x['date']<=target][-21:],target)
            if sr[-1]['volume']<=0: raise ValueError('NO_TRADE_ON_TARGET')
            tr=[];yr=[]
            tpath=a.prior/'raw'/(code+'-tencent-raw.json');ypath=a.prior/'raw'/(code+'-yahoo-raw.json')
            if tpath.exists():
                tb=json.loads(tpath.read_text())['data']['hk'+code].get('day',[])
                tr=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in tb if b[0]<=target]
                r['tencent_raw_sha256']=hashlib.sha256(tpath.read_bytes()).hexdigest()
            if ypath.exists():
                yr=json.loads(ypath.read_text())['rows'];r['yahoo_raw_sha256']=hashlib.sha256(ypath.read_bytes()).hexdigest()
            r['sina_vs_tencent']=whole_window_agrees(sr,tr,target)
            r['sina_vs_yahoo']=whole_window_agrees(sr,yr,target)
            if not r['sina_vs_tencent']['accepted']:
                # Yahoo support alone cannot validate the Tencent qfq input.
                raise ValueError('NO_FULL_WINDOW_SUPPORT_FOR_TENCENT_INPUT')
            q=parent['histories'][code].get('tencent') or []
            if not q:
                extra=a.parent.parent/'independent-raw'/(code+'.json')
                if extra.exists():
                    v=json.loads(extra.read_text())['data']['hk'+code];b=v.get('qfqday') or v.get('day') or []
                    q=[dict(zip(('date','open','close','high','low','volume'),x[:6])) for x in b]
            q=normalized([x for x in q if x['date']<=target][-21:],target)
            if [x['date'] for x in q]!=[x['date'] for x in sr] or any(x['volume']!=y['volume'] for x,y in zip(q,sr)):
                raise ValueError('ADJUSTED_WINDOW_OR_VOLUME_CONFLICT')
            r.update(status='THIRD_PUBLISHER_RAW_SUPPORT',input_source='Tencent:qfq',
                independent_adjustment_factor_verified=False,retains_original_conflict=True)
            return r,{'rows':q,'source':'Tencent:qfq+Sina_raw_support','recovery':True,
                'raw_proof':r['sina_vs_tencent'],'independent_history_full_window_passed':False}
        except Exception as exc:
            msg=str(exc);r['reason']=msg if msg.replace('_','').isalnum() and len(msg)<100 else type(exc).__name__
            return r,None
    results=[];new={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i,(row,data) in enumerate(pool.map(one,isolated),1):
            results.append(row)
            if data: new[row['code']]=data
            if i%10==0:print(json.dumps({'processed':i,'denominator':62}),flush=True)
    out={'run_id':s['run_id'],'target_session':target,'generated_at':datetime.now(timezone.utc).isoformat(),
        'O_denominator':660,'prior_ready':598,'reviewed_isolations':len(results),'new_supported':len(new),
        'new_input_ready':598+len(new),'remaining_isolated':62-len(new),
        'rows':results,'reason_counts':dict(Counter(x.get('reason','PASS') for x in results)),
        'input_contract':'RUN043_PROSPECTIVE_THIRD_PUBLISHER_REPAIR_v1',
        'prior_sha256':s['prior_sha256'],'historical_predictions_modified':False,
        'adjustment_note':'Third source validates raw OHLCV only; adjusted-series readiness is distinct from full adjustment-factor verification.',
        'native_predictions':0,'model_requests':0,'cost_cny':'0'}
    (a.out/'THIRD_SOURCE_RESULT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    (a.out/'PROSPECTIVE_INPUTS.json').write_text(json.dumps({'contract':out['input_contract'],'target':target,
        'O_denominator':660,'inputs':{**prior['inputs'],**new}},allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='rows'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
