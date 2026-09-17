"""Execute accepted current Run006 inputs through unchanged native data CLI."""
import argparse,json,hashlib,os,subprocess,sys,runpy
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from run032_native_recovery4 import UPSTREAM


def load(recovery,universe):
    r=json.loads(recovery.read_text());u=json.loads(universe.read_text());codes=[x['code'] for x in u['members']]
    assert r['contract_id'] in {'RUN006_B1_HK_DAILY_RECOVERY_V1','RUN045_THIRD_PUBLISHER_INPUT_REPAIR_v1'} and r['O_denominator']==len(codes)==len(set(codes))==660
    if r['contract_id']=='RUN045_THIRD_PUBLISHER_INPUT_REPAIR_v1':
        assert r['parent_contract_id']=='RUN006_B1_HK_DAILY_RECOVERY_V1'
        assert len(r['parent_recovery_sha256'])==len(r['third_result_sha256'])==64
        repaired=[x for x in r['rows'] if x['route']=='THIRD_PUBLISHER_RECOVERY']
        assert len(repaired)==r['new_recovered']
        assert all(x['third_publisher_proof']['status'] in {'SINA_SUPPORTS_TENCENT_RAW','SINA_SUPPORTS_ORIGINAL_YAHOO'} for x in repaired)
    assert {x['code'] for x in r['rows']}==set(codes) and set(r['inputs'])=={x['code'] for x in r['rows'] if x['route']!='ISOLATED'}
    from audit_dual_history_cache import normalized
    for c,item in r['inputs'].items():assert len(normalized(item['rows'],r['target']))==21
    return r,codes


def main():
    p=argparse.ArgumentParser()
    for k in ['checkout','recovery','universe','out']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--child',action='store_true');a=p.parse_args();r,codes=load(a.recovery,a.universe);checkout=a.checkout.resolve();out=a.out.resolve()
    if a.child:
        os.chdir(checkout);sys.path.insert(0,str(checkout));os.environ['DATABASE_PATH']=str(out/'native-data.db')
        import pandas as pd
        from data_provider.base import DataFetcherManager,DataFetchError
        from data_provider.tencent_fetcher import TencentFetcher
        def get_daily(self,stock_code,start_date=None,end_date=None,days=30):
            code=str(stock_code).upper().removeprefix('HK')
            if code not in r['inputs']:raise DataFetchError('RUN006_CURRENT_INPUT_ISOLATED_NO_NETWORK_FALLBACK')
            rows=r['inputs'][code]['rows']
            if (start_date and str(start_date)[:10]>rows[0]['date']) or (end_date and str(end_date)[:10]<r['target']):raise DataFetchError('RUN006_REQUEST_WINDOW_CONFLICT')
            f=TencentFetcher();frame=f._calculate_indicators(f._clean_data(f._normalize_data(pd.DataFrame(rows),stock_code)))
            return frame,r['contract_id']+':'+r['inputs'][code]['source']
        sys.argv=['main.py','--stocks',','.join('hk'+c for c in codes),'--dry-run','--no-notify','--no-market-review','--force-run','--workers','3']
        with patch.object(DataFetcherManager,'get_daily_data',get_daily):runpy.run_path(str(checkout/'main.py'),run_name='__main__')
        return
    out.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()==UPSTREAM
    assert not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=checkout,text=True).strip()
    env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ('TOKEN','API_KEY','SECRET','WEBHOOK'))};env.update(ENV_FILE='/dev/null',BACKTEST_ENABLED='false',NEWS_INTEL_AUTO_FETCH_ENABLED='false',ENABLE_REALTIME_QUOTE='false',PREFETCH_REALTIME_QUOTES='false',ENABLE_REALTIME_TECHNICAL_INDICATORS='false')
    with (out/'native.log').open('w') as log:
        cmd=[sys.executable,str(Path(__file__).resolve()),'--checkout',str(checkout),'--recovery',str(a.recovery.resolve()),'--universe',str(a.universe.resolve()),'--out',str(out),'--child'];q=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    from run_hk_native_data_probe import audit_database,export_market_history
    coverage=audit_database(out/'native-data.db',['hk'+c for c in codes],r['target']);passed={x['code'][2:] for x in coverage if x['status']=='current_valid_bar'}
    assert passed==set(r['inputs']),'NATIVE_CONSUMPTION_COUNT_OR_IDENTITY_MISMATCH'
    cache=export_market_history(out/'native-data.db',['hk'+c for c in codes],r['target'],out/'market-history.json')
    result={'run_id':r.get('native_acceptance_run_id','TRI-DSA-EXEC-20260917-036'),'input_contract':r['contract_id'],'workflow_run':os.environ.get('GITHUB_RUN_ID'),'upstream':UPSTREAM,'target':r['target'],'recovery_sha256':hashlib.sha256(a.recovery.read_bytes()).hexdigest(),'denominator':660,'actual_native_data_ready':len(passed),'isolated':660-len(passed),'formal_native_model_outputs':0,'native_model_http_requests':0,'fee_cny':'0','scope':'Actual frozen native data CLI consumption of21-session inputs under stated prospective input contract; not LLM outputs or trade signals','native_returncode':q.returncode,'historical_predictions_modified':False,'source_strategy_modified':False,'market_history_sha256':cache,'coverage':coverage,'completed_at':datetime.now(timezone.utc).isoformat()}
    (out/'NATIVE_RECOVERY_ACCEPTANCE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('NATIVE_RECOVERY_ACCEPTANCE '+json.dumps({k:v for k,v in result.items() if k!='coverage'},ensure_ascii=False))
if __name__=='__main__':main()
