"""Zero-model diagnostic for pool preflight cross-provider disagreements."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import requests
from prepare_hk_pool_rollout_preflight import normalize_native, tencent_rows, OHLC_TOLERANCE, LATEST_VOLUME_MAX_RELATIVE_DEVIATION

def one(code,target,cache):
    native=normalize_native((cache.get('histories') or {}).get('hk'+code) or [],target)
    r=requests.get('https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get',
                   params={'param':f'hk{code},day,,,180,qfq'},timeout=(8,18))
    r.raise_for_status()
    independent=tencent_rows(r.json(),code,target)
    by={x['date']:x for x in independent}
    pairs=[(x,by[x['date']]) for x in native if x['date'] in by]
    mismatches=[]
    for left,right in pairs:
        fields=[]
        for k in ('open','high','low','close'):
            delta=abs(float(left[k])-float(right[k]))
            if delta>OHLC_TOLERANCE+1e-9: fields.append({'field':k,'delta':delta,'native':left[k],'tencent':right[k]})
        if fields:mismatches.append({'date':left['date'],'fields':fields})
    latest=next((p for p in pairs if p[0]['date']==target),None)
    if latest:
        lv,rv=float(latest[0]['volume']),float(latest[1]['volume'])
        vdev=0.0 if lv==rv else (None if lv==0 or rv==0 else abs(lv/rv-1.0))
        latest_fields={k:{
            'native':latest[0][k],'tencent':latest[1][k],
            'delta':abs(float(latest[0][k])-float(latest[1][k])),
            'within_tolerance':abs(float(latest[0][k])-float(latest[1][k]))<=OHLC_TOLERANCE+1e-9,
        } for k in ('open','high','low','close')}
    else:
        vdev=None;latest_fields=None
    return {
        'code':code,'target':target,'native_count':len(native),'tencent_count':len(independent),'overlap':len(pairs),
        'ohlc_mismatch_sessions':len(mismatches),
        'first_mismatch':mismatches[0] if mismatches else None,
        'last_mismatch':mismatches[-1] if mismatches else None,
        'recent_mismatch_dates':[x['date'] for x in mismatches[-10:]],
        'target_ohlc':latest_fields,
        'target_ohlc_all_within_tolerance':bool(latest_fields and all(v['within_tolerance'] for v in latest_fields.values())),
        'target_volume_relative_deviation':vdev,
        'target_volume_within_calibrated_bound':bool(vdev is not None and vdev<=LATEST_VOLUME_MAX_RELATIVE_DEVIATION+1e-12),
        'independent_source_sha256':hashlib.sha256(r.content).hexdigest(),
        'retrieved_at':datetime.now(timezone.utc).isoformat(),
    }

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--cache',type=Path,required=True);ap.add_argument('--target',required=True);ap.add_argument('--codes',required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();cache=json.loads(a.cache.read_text());rows=[one(c,a.target,cache) for c in a.codes.split(',')]
    result={'schema_version':1,'run_id':'TRI-DSA-O-INDEPENDENT-DIAG-20260918-058C','target_session':a.target,'members':rows,'model_http_requests':0,'paid_data_calls':0,'real_orders':0}
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
