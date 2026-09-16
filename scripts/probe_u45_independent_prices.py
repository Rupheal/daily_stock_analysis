#!/usr/bin/env python3
"""Model-free U45 target-session Tencent/Yahoo cross-provider readiness probe.

This is a deterministic preparation check, not strategy acceptance. It verifies
that both free providers expose the same target session and applies the already
frozen HK OHLC/volume reconciliation semantics to the target bar only.
"""
from __future__ import annotations
import argparse,json
from datetime import date,timedelta
from pathlib import Path
import pandas as pd,requests,yfinance as yf
from data_provider.tencent_fetcher import _extract_kline_rows
from src.services.hk_volume_reconciliation import validate_latest_session,validate_ohlc_pairs,reconcile_volume_pairs,PriceVolumeReconciliationError,CALIBRATION_RUN_ID

def tencent(code):
    symbol='hk'+code
    r=requests.get('https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get',params={'param':f'{symbol},day,,,80,qfq'},timeout=20);r.raise_for_status()
    rows=_extract_kline_rows(r.json(),symbol=symbol)
    return pd.DataFrame(rows)

def yahoo(code,target):
    ticker=f'{int(code):04d}.HK'
    h=yf.Ticker(ticker).history(start=(target-timedelta(days=120)).isoformat(),end=(target+timedelta(days=1)).isoformat(),auto_adjust=True,actions=True,timeout=20)
    if h.empty:return h
    h=h.reset_index();h.columns=[str(x).lower() for x in h.columns];h['date']=pd.to_datetime(h['date']).dt.strftime('%Y-%m-%d');return h

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--universe',required=True);ap.add_argument('--target',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();target=date.fromisoformat(a.target);u=json.loads(Path(a.universe).read_text(encoding='utf-8'));assert u['member_count']==45 and len(u['members'])==45
    out=[]
    for m in u['members']:
        code=m['code'];rec={'code':code,'target_session':a.target,'fallback_available':False,'provider_target_crosscheck':False,'status':'PROVIDER_BLOCKED','error_code':None}
        try:
            t=tencent(code); y=yahoo(code,target)
            if t.empty or y.empty: raise ValueError('PROVIDER_EMPTY')
            t['date']=pd.to_datetime(t['date']).dt.strftime('%Y-%m-%d');t=t[t['date']<=a.target].sort_values('date');y=y[y['date']<=a.target].sort_values('date')
            if t.empty or y.empty: raise ValueError('TARGET_WINDOW_EMPTY')
            tr=t.iloc[-1];yr=y.iloc[-1];rec['tencent_latest']=str(tr['date']);rec['yahoo_latest']=str(yr['date']);rec['fallback_available']=True
            validate_latest_session(str(tr['date']),str(yr['date']),a.target)
            validate_ohlc_pairs((f,float(tr[f]),float(yr[f])) for f in ('open','high','low','close'))
            v=reconcile_volume_pairs([(a.target,float(tr['volume']),float(yr['volume']))],a.target,unit_semantics_verified=True)
            rec.update(provider_target_crosscheck=True,status='PROVIDER_READY',volume_status=v['latest_session_status'],volume_relative_deviation=v['latest_session_relative_deviation'],calibration_run_id=CALIBRATION_RUN_ID)
        except PriceVolumeReconciliationError as exc:
            rec['error_code']=str(exc)
        except Exception as exc:
            rec['error_code']=type(exc).__name__+':'+str(exc)[:120]
        out.append(rec)
    ready=sum(x['provider_target_crosscheck'] for x in out)
    payload={'schema_version':'U45_PROVIDER_READINESS_v1','target_session':a.target,'denominator':45,'provider_ready':ready,'provider_blocked':45-ready,'model_calls':0,'paid_data_calls':0,'scope':'target-session Tencent/Yahoo crosscheck only','members':out}
    Path(a.out).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'provider_ready':ready,'provider_blocked':45-ready,'model_calls':0}))
if __name__=='__main__':main()
