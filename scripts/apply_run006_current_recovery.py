"""Apply the frozen Run006 21-session routing contract to a new input snapshot.

Never rewrites Run005, Run006 or Run033. Public raw comparisons precede fallback.
"""
import argparse,hashlib,json,math,os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
import requests,yfinance as yf
from audit_dual_history_cache import normalized,compare


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def recent(rows,target):return normalized([r for r in rows if str(r['date'])[:10]<=target][-21:],target)
def raw_agreement(left,right,target):
    y={r['date']:r for r in left};t={r['date']:r for r in right};days=sorted(set(y)&set(t))[-21:]
    if len(days)!=21 or days[-1]!=target:return {'class':'RAW_WINDOW_INCOMPLETE','days':len(days)}
    tight=loose=True;volume=True;diffs=[]
    for day in days:
        for field in ('open','high','low','close'):
            a,b=float(y[day][field]),float(t[day][field]);d=abs(a-b)
            if not math.isfinite(a+b) or min(a,b)<=0:raise ValueError('INVALID_RAW_PRICE')
            tight &= d<=max(.01,.001*abs(b))+1e-9;loose &= d<=max(.02,.002*abs(b))+1e-9
            if d>max(.02,.002*abs(b))+1e-9:diffs.append({'date':day,'field':field,'yahoo_raw':a,'tencent_raw':b})
        volume &= y[day]['volume']==t[day]['volume']
    return {'class':'RAW_PRICE_AGREEMENT_TIGHT' if tight else 'RAW_PRICE_AGREEMENT_LOOSE' if loose else 'RAW_SOURCE_CONFLICT','days':21,'exact_volume_agreement':volume,'conflict_examples':diffs[:3]}


def main():
    p=argparse.ArgumentParser()
    for k in ['parent','native','contract','universe','u-universe','out']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--prior-recovery',type=Path);p.add_argument('--run-id',default='TRI-DSA-EXEC-20260917-035')
    a=p.parse_args();parent=json.loads(a.parent.read_text());native=json.loads(a.native.read_text());contract=json.loads(a.contract.read_text());u=json.loads(a.universe.read_text());uu=json.loads(a.u_universe.read_text());target=parent['target_session']
    assert contract['contract_id']=='RUN006_B1_HK_DAILY_RECOVERY_V1' and contract['feature_contract']['lookback_trading_sessions']==21 and contract['frozen_prediction_firewall']['future_runs_only']
    assert u['member_count']==len(u['members'])==660 and parent['universe_sha256']==digest(a.universe)
    prior=json.loads((a.prior_recovery/'CURRENT_RECOVERY.json').read_text()) if a.prior_recovery else None
    if prior:assert prior['parent_cache_sha256']==digest(a.parent) and prior['target']==target and prior['contract_sha256']==digest(a.contract)
    previous={r['code']:r for r in prior['rows']} if prior else {}
    a.out.mkdir(parents=True,exist_ok=False);rawdir=a.out/'raw';rawdir.mkdir();now=datetime.now(timezone.utc).isoformat();rows=[];inputs={}
    def one(m):
        code=m['code'];r={'code':code,'target':target,'route':'ISOLATED','reasons':[]};src=parent['histories'][code];nr=native['histories'].get('hk'+code,[]);qb=src.get('tencent') or []
        try:
            prev=previous.get(code,{})
            if prev.get('route')!='ISOLATED' and prev:
                return dict(prev,reused_prior_recovery=True),prior['inputs'][code]
            if prev.get('reasons') in [['ValueError:TARGET_MISSING'],['ValueError:LESS_THAN_21_BARS']]:
                return dict(prev,reused_prior_isolation=True),None
            # Even parent-normalization failures retain original provider bytes in the raw artifact.
            if not qb:
                independent=a.parent.parent/'independent-raw'/(code+'.json')
                if independent.exists():
                    item=json.loads(independent.read_text())['data']['hk'+code];bb=item.get('qfqday') or item.get('day') or []
                    qb=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in bb]
                else:
                    response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get',params={'param':f'hk{code},day,,,180,qfq'},timeout=20);response.raise_for_status();raw=response.content;(rawdir/(code+'-qfq.json')).write_bytes(raw);item=response.json()['data']['hk'+code];bb=item.get('qfqday') or item.get('day') or [];qb=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in bb];r['new_qfq_sha256']=hashlib.sha256(raw).hexdigest();r['new_qfq_source']=response.url
            q=recent(qb,target)
            if q[-1]['volume']==0:raise ValueError('NO_TRADE_ON_TARGET_REQUIRES_STATUS')
            try:n=recent(nr,target);orig=compare(n,q,target);nvalid=True
            except (ValueError,TypeError):n=[];orig={'independent_history_passed':False};nvalid=False
            if orig['independent_history_passed']:
                r['route']='KEEP_ORIGINAL_PROVIDER';r['input_source']='native';return r,{'rows':n,'source':'native-original','recovery':False}
            end=datetime.fromisoformat(target)+timedelta(days=1);start=end-timedelta(days=65)
            cached_yahoo=a.prior_recovery/'raw'/(code+'-yahoo-raw.json') if a.prior_recovery else None
            if cached_yahoo and cached_yahoo.exists():
                yr=json.loads(cached_yahoo.read_text())['rows'];f=None;r['yahoo_raw_reused_sha256']=digest(cached_yahoo)
            else:
                f=yf.Ticker(f'{int(code):04d}.HK').history(start=start.date().isoformat(),end=end.date().isoformat(),auto_adjust=False,actions=True,repair=False,timeout=20);yr=[]
            for idx,v in (f.iterrows() if f is not None else []):
                if str(idx)[:10]>target:continue
                z={'date':str(idx)[:10]}
                for sk,k in [('Open','open'),('High','high'),('Low','low'),('Close','close'),('Volume','volume')]:z[k]=float(v[sk])
                z['dividends']=float(v.get('Dividends',0));z['stock_splits']=float(v.get('Stock Splits',0));yr.append(z)
            yp=rawdir/(code+'-yahoo-raw.json')
            if cached_yahoo and cached_yahoo.exists():yp.write_bytes(cached_yahoo.read_bytes())
            else:yp.write_text(json.dumps({'provider':'Yahoo yfinance auto_adjust=False repair=False','retrieved_at':datetime.now(timezone.utc).isoformat(),'source_locator':f'https://query1.finance.yahoo.com/v8/finance/chart/{int(code):04d}.HK','rows':yr},allow_nan=False))
            r['yahoo_raw_sha256']=digest(yp)
            response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/kline/kline',params={'param':f'hk{code},day,,,180'},timeout=20);response.raise_for_status();raw=response.content;tp=rawdir/(code+'-tencent-raw.json');tp.write_bytes(raw);r['tencent_raw_sha256']=digest(tp);r['tencent_raw_source']=response.url;r['raw_available_at']=datetime.now(timezone.utc).isoformat();bb=response.json()['data']['hk'+code].get('day') or [];tr=[dict(zip(('date','open','close','high','low','volume'),b[:6])) for b in bb if b[0]<=target];tr=recent(tr,target)
            # Run006's existing provider-gap rule does not require unavailable Yahoo history.
            # Preserve the missing-source disclosure; this is not independent full-history proof.
            if len(yr)<21 or not yr or yr[-1]['date']!=target:
                if not nr or len(nr)<21 or str(nr[-1]['date'])[:10]!=target:
                    r.update(route='USE_TENCENT_QFQ_FALLBACK',reason='RUN006_PROVIDER_HISTORY_GAP',input_source='Tencent:qfq',independent_full_history_verified=False)
                    return r,{'rows':q,'source':'Tencent:qfq','recovery':True,'independent_history_full_window_passed':False}
            ag=raw_agreement(yr,tr,target);r['raw_comparison']=ag
            if ag['class'] not in ['RAW_PRICE_AGREEMENT_TIGHT','RAW_PRICE_AGREEMENT_LOOSE']:raise ValueError(ag['class'])
            # Run006 specifies raw price boundaries, not a new volume tolerance. Disagreement stays isolated.
            if not ag['exact_volume_agreement']:raise ValueError('RAW_VOLUME_CONFLICT')
            r.update(route='USE_TENCENT_QFQ_FALLBACK',reason='RAW_SOURCE_AGREEMENT_AFTER_ADJUSTED_OR_PROVIDER_FAILURE',input_source='Tencent:qfq',original_21_geometry_valid=nvalid)
            return r,{'rows':q,'source':'Tencent:qfq','recovery':True,'raw_proof':ag,'independent_history_full_window_passed':False}
        except Exception as exc:
            r['reasons']=[type(exc).__name__+':'+str(exc)[:130]];return r,None
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i,(r,v) in enumerate(pool.map(one,u['members']),1):
            rows.append(r)
            if v:inputs[r['code']]=v
            if i%100==0:print(json.dumps({'run':'Run035','processed':i,'denominator':660}),flush=True)
    c=Counter(r['route'] for r in rows);u_codes={x['code'] for x in uu['members']}
    out={'run_id':a.run_id,'prior_recovery_sha256':digest(a.prior_recovery/'CURRENT_RECOVERY.json') if a.prior_recovery else None,'workflow_run':os.environ.get('GITHUB_RUN_ID'),'contract_id':contract['contract_id'],'contract_sha256':digest(a.contract),'parent_cache_sha256':digest(a.parent),'target':target,'generated_at':datetime.now(timezone.utc).isoformat(),'O_denominator':660,'U_denominator':45,'routes':dict(c),'O_recovery_contract_input_ready':len(inputs),'U_recovery_contract_input_ready':len(u_codes&set(inputs)),'U_missing_from_O_cache':sorted(u_codes-set(parent['histories'])),'failure_counts':dict(Counter(f for r in rows for f in r['reasons'])),'rows':rows,'inputs':inputs,'model_requests':0,'fee_cny':'0','prediction_effectiveness_claimed':False,'native_model_outputs':0,'original_source_modified':False,'historical_frozen_runs_modified':False}
    path=a.out/'CURRENT_RECOVERY.json';path.write_text(json.dumps(out,ensure_ascii=False,allow_nan=False)+'\n')
    print('CURRENT_RECOVERY_SUMMARY '+json.dumps({k:v for k,v in out.items() if k not in ['rows','inputs']},ensure_ascii=False),flush=True)
    print('CURRENT_RECOVERY_SHA256 '+digest(path),flush=True)
if __name__=='__main__':main()
