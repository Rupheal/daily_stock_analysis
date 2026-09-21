#!/usr/bin/env python3
"""Freeze an exact-session formal snapshot or a separately labelled R0 snapshot."""
from __future__ import annotations
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
import exchange_calendars as xcals
from freeze_hk_connect_universe import freeze,freeze_r0_membership
from dsa_snapshot_r0_contract_v1 import materialize_r0
URLS={
 'sse-list.json':'https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L&isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&keyword=',
 'szse-list.json':'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1',
 'szse-list.xlsx':'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1',
 'hkex-securities.xlsx':'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'}

def identity_sessions_for_daily_snapshot(session:str):
    cal=xcals.get_calendar('XHKG');cur=cal.date_to_session(session,direction='none')
    return [cur.date().isoformat()]  # Previous-session identity is NOT current formal identity.

def build_from_r0_seal(session,u_universe,prior_o_identity,seal_path,out):
    return materialize_r0(session,u_universe,prior_o_identity,seal_path,out)

def build(session:str,u_universe:Path,out:Path,prior_o_identity:Path|None=None,r0_seal:Path|None=None):
    identity_sessions_for_daily_snapshot(session)
    if r0_seal is None:
        auto=Path(__file__).resolve().parents[1]/'docs/runtime'/('DSA_R0_MEMBERSHIP_SEAL_'+session.replace('-','')+'.json')
        r0_seal=auto if auto.exists() else None
    if r0_seal is not None and r0_seal.exists():
        if prior_o_identity is None:raise ValueError('R0_SEAL_REQUIRES_PRIOR_IDENTITY')
        return build_from_r0_seal(session,u_universe,prior_o_identity,r0_seal,out)
    src=out/'sources';src.mkdir(parents=True,exist_ok=False);rows=[]
    for name,url in URLS.items():
        started=datetime.now(timezone.utc).isoformat()
        for attempt in range(3):
            try:
                h={'User-Agent':'Mozilla/5.0','Accept':'*/*','Referer':'https://www.sse.com.cn/'}
                if 'szse.cn' in url:h['Referer']='https://www.szse.cn/'
                if 'hkex.com.hk' in url:h['Referer']='https://www.hkex.com.hk/'
                resp=requests.get(url,headers=h,timeout=(10,30));resp.raise_for_status();raw=resp.content
                if not raw:raise RuntimeError('EMPTY_SOURCE')
                (src/name).write_bytes(raw)
                rows.append({'file':name,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'status':'received','bytes':len(raw)})
                break
            except Exception:
                if attempt==2:raise
                time.sleep(1+attempt)
    (src/'source-probe.json').write_text(json.dumps({'schema_version':1,'sources':rows},indent=2)+'\n')
    mode='FORMAL_IDENTITY_EXACT_SESSION'
    try:
        o,u=freeze(src,session,u_universe,allowed_identity_sessions=[session])
        for name,obj in [('O_UNIVERSE',o),('U_UNIVERSE',u)]:(out/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
        o_r0={**o,'r0_membership_verified':True};u_r0={**u,'r0_membership_verified':True}
    except ValueError as exc:
        if not str(exc).startswith('HKEX_IDENTITY_DATE_UNVERIFIED:') or prior_o_identity is None:raise
        actual=str(exc).split(':')[1]
        if actual<=session:raise
        prior=json.loads(prior_o_identity.read_text());asof=prior.get('effective_session')
        if not asof or asof>session:raise ValueError('R0_PRIOR_IDENTITY_DATE_UNVERIFIED')
        mode='R0_FUTURE_HKEX_IDENTITY_NOT_USED'
        o_r0,u_r0=freeze_r0_membership(src,session,u_universe,prior_o_identity)
        for obj in (o_r0,u_r0):
            obj.update(full_union_verified=False,formal_stock_universe_verified=False)
            for m in obj.get('members',[]):m.update(identity_verified=False,formal_identity_current_session_verified=False,board_lot=None,isin=None,currency=None,execution_eligibility='R0_ONLY_NOT_EXECUTION_ELIGIBILITY')
        o,u=None,None
    for name,obj in [('O_R0_UNIVERSE',o_r0),('U_R0_UNIVERSE',u_r0)]:(out/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    status={'schema_version':2,'target_session':session,'mode':mode,'formal_universe_available':o is not None and u is not None,'O_r0_denominator':o_r0['member_count'],'U_denominator':45,'identity_pending_count':o_r0.get('identity_pending_count',0),'future_identity_master':o_r0.get('future_identity_master'),'paid_model_calls':0,'real_orders':0}
    (out/'SNAPSHOT_STATUS.json').write_text(json.dumps(status,indent=2)+'\n');return status

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--session',required=True);ap.add_argument('--u-universe',type=Path,required=True)
    ap.add_argument('--prior-o-identity',type=Path,default=Path('docs/runtime/run032_public_cache/O_UNIVERSE.json'))
    ap.add_argument('--r0-seal',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=False);print(json.dumps(build(a.session,a.u_universe,a.out,a.prior_o_identity,a.r0_seal)))
if __name__=='__main__':main()
