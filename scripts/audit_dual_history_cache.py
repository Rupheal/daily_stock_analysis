"""Public market cache and independent history audit; never model acceptance."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import requests
from run032_native_recovery4 import load_cache


def normalized(rows, target):
    out=[]
    for r in rows:
        row={k:r.get(k) for k in ('date','open','high','low','close','volume','amount','data_source')}
        row['date']=str(row['date'])[:10]
        if row['date']>target: raise ValueError('FUTURE_BAR_IN_EXPORTED_CACHE')
        for k in ('open','high','low','close','volume'):
            if isinstance(row[k],bool):raise ValueError('INVALID_MARKET_NUMBER')
            row[k]=float(row[k])
            if not math.isfinite(row[k]):raise ValueError('NONFINITE_MARKET_NUMBER')
        if not 0<row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high'] or row['volume']<0:raise ValueError('INVALID_BAR_GEOMETRY')
        out.append(row)
    dates=[x['date'] for x in out]
    if dates!=sorted(set(dates)):raise ValueError('DUPLICATE_OR_UNSORTED_HISTORY')
    if not out or dates[-1]!=target:raise ValueError('TARGET_MISSING')
    if len(out)<21:raise ValueError('LESS_THAN_21_BARS')
    return out


def tencent_rows(payload,code,target):
    item=payload['data']['hk'+code]
    rows=item.get('qfqday') or item.get('day') or []
    return normalized([dict(zip(('date','open','close','high','low','volume'),r[:6])) for r in rows if r[0]<=target],target)


def compare(primary, independent, target, independent_sources=True):
    by={r['date']:r for r in independent};pairs=[(r,by[r['date']]) for r in primary if r['date'] in by]
    findings=[]
    if len(pairs)<21:findings.append('INDEPENDENT_OVERLAP_LT_21')
    for left,right in pairs:
        for k in ('open','high','low','close'):
            if abs(left[k]-right[k])>0.005+1e-9:findings.append('OHLC_OR_ADJUSTMENT_DISAGREEMENT');break
        # The single-stock calibrated volume margin is not generalized to every issuer.
        if left['volume']!=right['volume']:findings.append('VOLUME_DISAGREEMENT')
    if not independent_sources:findings.append('SAME_PROVIDER_NOT_INDEPENDENT_HISTORY')
    return {'overlap_sessions':len(pairs),'independent_history_passed':not findings,
            'failures':sorted(set(findings)),'price_absolute_tolerance':0.005,'volume_rule':'EXACT_ONLY_NO_NEW_POOL_TOLERANCE',
            'ma60_history_present':len(primary)>=60 and len(independent)>=60}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--native',type=Path,required=True);ap.add_argument('--universe',type=Path,required=True);ap.add_argument('--u-universe',type=Path,required=True);ap.add_argument('--recovery-cache',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    native=json.loads(a.native.read_text());u=json.loads(a.universe.read_text());uu=json.loads(a.u_universe.read_text());target=native['target_session'];codes=[x['code'] for x in u['members']]
    assert len(codes)==u['member_count']==len(set(codes))==native['requested_denominator'] and u['full_union_verified']
    m,recovered=load_cache(a.recovery_cache);assert target==m['target']
    records=[];histories={};rawdir=a.out/'independent-raw';rawdir.mkdir()
    def one(code):
        rec={'code':code,'target_session':target,'history_saved':False,'independent_history_passed':False,'failures':[]}
        try:
            rows=native['histories'].get('hk'+code,[])
            from_recovery=not rows and code in recovered
            if from_recovery: rows=[dict(r,data_source='TencentHK:Run006_verified_recovery_v1') for r in recovered[code]]
            bars=normalized(rows,target)
            rec.update(history_saved=True,bars=len(bars),source_counts=dict(Counter(r.get('data_source') or 'unrecorded' for r in bars)),recovery_input=from_recovery)
            if from_recovery:
                file=a.recovery_cache/(code+'-tencent.json');raw=file.read_bytes();source={'url':'https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk'+code+',day,,,90,qfq','retrieved_at':m.get('created_at') or m.get('frozen_at'),'reused_source_cache':True,'sha256':hashlib.sha256(raw).hexdigest()}
            else:
                response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get',params={'param':f'hk{code},day,,,180,qfq'},timeout=(8,18));response.raise_for_status();raw=response.content
                source={'url':response.url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'reused_source_cache':False,'sha256':hashlib.sha256(raw).hexdigest()}
            (rawdir/(code+'.json')).write_bytes(raw)
            independent=tencent_rows(json.loads(raw),code,target)
            rec.update(compare(bars,independent,target,not from_recovery and all('Tencent' not in str(r.get('data_source')) for r in bars)))
            rec['independent_source']=source
            return rec,{'native':bars,'tencent':independent,'independent_source':source}
        except Exception as exc:
            rec['failures']=[type(exc).__name__+':'+str(exc)[:140]]
            return rec,{'native':locals().get('bars',[]),'tencent':[]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for i,(r,h) in enumerate(pool.map(one,codes),1):
            records.append(r);histories[r['code']]=h
            if i%100==0:print(json.dumps({'processed':i,'denominator':len(codes)}),flush=True)
    def save(name,value):
        p=a.out/name;p.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');return hashlib.sha256(p.read_bytes()).hexdigest()
    cache_sha=save('HISTORY_CACHE.json',{'schema':'DSA_DUAL_REUSABLE_HISTORY_v1','target_session':target,'universe_sha256':hashlib.sha256(a.universe.read_bytes()).hexdigest(),'native_export_sha256':hashlib.sha256(a.native.read_bytes()).hexdigest(),'histories':histories,'raw_models_included':False,'collected_at':datetime.now(timezone.utc).isoformat()})
    u_codes={x['code'] for x in uu['members']};u_rows=[x for x in records if x['code'] in u_codes]
    missing=sorted(u_codes-set(codes))
    result={'run_id':'TRI-DSA-EXEC-20260917-033','workflow_run':__import__('os').getenv('GITHUB_RUN_ID'),'target_session':target,'decision_session':u['effective_session'],'O_denominator':len(codes),'O_history_saved':sum(x['history_saved'] for x in records),'O_independent_history_passed':sum(x['independent_history_passed'] for x in records),'O_failure_counts':dict(Counter(f for x in records for f in x['failures'])),'U_denominator':45,'U_in_O_pool':len(u_rows),'U_independent_history_passed':sum(x['independent_history_passed'] for x in u_rows),'U_not_in_current_O_union':missing,'cache_sha256':cache_sha,'members':records,'model_http_requests':0,'formal_outputs_accepted':0,'qualified_signals':0,'model_fee_cny':'0','future_price_rows_in_cache':False,'historical_prediction_modified':False,'scope':'Reusable inputs and strict public history comparison only; not native model rankings or strategy promotion'}
    save('HISTORY_READINESS.json',result)
    print('HISTORY_READINESS_SUMMARY '+json.dumps({k:v for k,v in result.items() if k!='members'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
