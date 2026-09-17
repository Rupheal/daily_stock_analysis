"""Explicit Run006 input recovery for failed HK codes; no frozen strategy edits."""
import argparse,hashlib,json,math,os,subprocess,sys,runpy
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch

UPSTREAM='089d9d26d68f8b839ea5a74a3784e4402925f8b7'

def validated_rows(raw,code,target,official):
    item=raw['data']['hk'+code];bars=item.get('qfqday') or item.get('day') or []
    rows=[]
    for z in bars:
        if z[0]>target:continue
        o,c,h,l,v=map(float,z[1:6])
        if not all(math.isfinite(x) for x in (o,c,h,l,v)) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError('INVALID_RECOVERY_GEOMETRY')
        rows.append({'date':z[0],'open':o,'close':c,'high':h,'low':l,'volume':v,'amount':None})
    if len(rows)<21 or rows[-1]['date']!=target or [x['date'] for x in rows]!=sorted({x['date'] for x in rows}):raise ValueError('INCOMPLETE_RECOVERY_HISTORY')
    last=rows[-1]
    for key in ('high','low','close','volume'):
        if official.get(key) is None or abs(float(official[key])-last[key])>1e-8:raise ValueError('OFFICIAL_RECOVERY_DISAGREEMENT:'+key)
    return rows

def load_cache(root):
    root=Path(root);m=json.loads((root/'MANIFEST.json').read_text())
    for name,sha in m['source_hashes'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('RECOVERY_SOURCE_HASH_CHANGED')
    official=json.loads((root/'hkex-20260916.json').read_text())
    if official['price_session']!=m['target']:raise ValueError('RECOVERY_SESSION_MISMATCH')
    return m,{c:validated_rows(json.loads((root/(c+'-tencent.json')).read_text()),c,m['target'],official['rows']['HK'+c]) for c in m['codes']}

def child(checkout,cache,db):
    m,data=load_cache(cache);os.chdir(checkout);sys.path.insert(0,str(checkout));os.environ['DATABASE_PATH']=str(db)
    import pandas as pd
    from data_provider.base import DataFetcherManager
    from data_provider.tencent_fetcher import TencentFetcher
    original=DataFetcherManager.get_daily_data
    def recovered(self,stock_code,start_date=None,end_date=None,days=30):
        code=str(stock_code).upper().removeprefix('HK')
        if code not in data:return original(self,stock_code,start_date,end_date,days)
        rows=data[code]
        rows=[r for r in rows if (not start_date or r['date']>=str(start_date)[:10]) and (not end_date or r['date']<=min(str(end_date)[:10],m['target']))]
        if len(rows)<21 or rows[-1]['date']!=m['target']:raise ValueError('NATIVE_REQUEST_RECOVERY_WINDOW_INCOMPLETE')
        f=TencentFetcher();frame=f._normalize_data(pd.DataFrame(rows),stock_code);frame=f._calculate_indicators(f._clean_data(frame))
        return frame,'TencentHK:Run006_verified_recovery_v1'
    sys.argv=['main.py','--stocks',','.join('hk'+c for c in m['codes']),'--dry-run','--no-notify','--no-market-review','--force-run','--workers','3']
    with patch.object(DataFetcherManager,'get_daily_data',recovered):runpy.run_path(str(checkout/'main.py'),run_name='__main__')

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkout',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--execute-child',action='store_true');a=p.parse_args();checkout=a.checkout.resolve();cache=a.cache.resolve();out=a.out.resolve()
    if a.execute_child:return child(checkout,cache,out/'native-data.db')
    m,data=load_cache(cache);out.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()==UPSTREAM
    assert not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=checkout,text=True).strip()
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('TOKEN','API_KEY','SECRET','WEBHOOK'))};env.update(ENV_FILE='/dev/null',NEWS_INTEL_AUTO_FETCH_ENABLED='false',BACKTEST_ENABLED='false',ENABLE_REALTIME_QUOTE='false',ENABLE_REALTIME_TECHNICAL_INDICATORS='false',PREFETCH_REALTIME_QUOTES='false')
    with (out/'native.log').open('w') as log:
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--checkout',str(checkout),'--cache',str(cache),'--out',str(out),'--execute-child'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
    from run_hk_native_data_probe import audit_database
    rows=audit_database(out/'native-data.db',['hk'+c for c in m['codes']],m['target']);passed=sum(x['status']=='current_valid_bar' for x in rows)
    result={'run_id':m['run_id'],'completed_at':datetime.now(timezone.utc).isoformat(),'parent_workflow_run':m['parent_workflow_run'],'upstream':UPSTREAM,'returncode':run.returncode,'subset_denominator':len(m['codes']),'subset_actual_native_data_ready':passed,'full_denominator':m['parent_denominator'],'parent_native_data_ready':m['parent_native_ready'],'composite_native_data_ready':m['parent_native_ready']+passed,'coverage':rows,'raw_snapshot_sha256':m['source_hashes'],'native_model_calls':0,'O_formal_accepted':0,'qualified_signals':0,'native_strategy_modified':False,'external_input_adapter':'Run006 verified Tencent HK cached recovery v1','independent_opening_price_verified':False,'full_historical_cross_source_validation':False,'source_note':'Amount unknown; HKEX compact daily page verifies high/low/close/shares, not opening. Current-day partial bars excluded.'}
    (out/'RECOVERY4_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
    if passed!=len(m['codes']) or run.returncode:raise SystemExit('NATIVE_RECOVERY_INCOMPLETE')
if __name__=='__main__':main()
