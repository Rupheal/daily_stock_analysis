#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
import exchange_calendars as xcals
from freeze_hk_connect_universe import freeze,freeze_r0_membership

URLS={
 'sse-list.json':'https://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_JYFW_HGT_XXPL_BDZQQD_L&isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&keyword=',
 'szse-list.json':'https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=SGT_GGTBDQD&TABKEY=tab1&PAGENO=1',
 'szse-list.xlsx':'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SGT_GGTBDQD&TABKEY=tab1',
 'hkex-securities.xlsx':'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx',
}
def identity_sessions_for_daily_snapshot(session:str):
    cal=xcals.get_calendar('XHKG')
    cur=cal.date_to_session(session,direction='none')
    prev=cal.previous_session(cur)
    return [cur.date().isoformat(),prev.date().isoformat()]

def build_from_r0_seal(session:str,u_universe:Path,prior_o_identity:Path,seal_path:Path,out:Path):
    seal=json.loads(seal_path.read_text())
    if seal.get('status')!='ACCEPTED_SAME_SESSION_R0_MEMBERSHIP_SEAL' or seal.get('target_session')!=session:
        raise ValueError('R0_MEMBERSHIP_SEAL_IDENTITY_INVALID')
    codes=[str(x).zfill(5) for x in seal.get('codes') or []]
    if len(codes)!=int(seal.get('membership_code_count',-1)) or len(codes)!=len(set(codes)):
        raise ValueError('R0_MEMBERSHIP_SEAL_DENOMINATOR_INVALID')
    prior=json.loads(prior_o_identity.read_text())
    if str(prior.get('effective_session') or '')>session:
        raise ValueError('R0_PRIOR_IDENTITY_IS_FUTURE')
    pmap={str(x.get('code') or '').zfill(5):x for x in prior.get('members') or []}
    om=[];pending=[]
    for code in codes:
        x=pmap.get(code)
        if x:
            om.append({**x,'code':code,'identity_status':'PIT_PRIOR_IDENTITY',
                       'identity_source_asof':prior.get('effective_session'),
                       'formal_identity_current_session_verified':False})
        else:
            pending.append(code)
            om.append({'code':code,'official_name':code,'english_name':None,'security_type':'UNRESOLVED',
                       'channels':[],'board_lot':None,'isin':None,'currency':None,
                       'identity_status':'SEALED_MEMBERSHIP_IDENTITY_PENDING',
                       'identity_source_asof':None,'formal_identity_current_session_verified':False})
    o={'schema_version':3,'effective_session':session,'universe_id':'O_R0_SEALED_'+session,
       'member_count':len(om),'members':om,'r0_membership_verified':True,
       'formal_stock_universe_verified':False,'identity_pending_codes':pending,
       'identity_pending_count':len(pending),'seal':{k:seal.get(k) for k in ('seal_id','source_workflow_run','source_artifact_id','source_artifact_digest','source_universe_sha256')},
       'not_available_for_earlier_decisions':True}
    u=json.loads(u_universe.read_text());assert len(u.get('members') or [])==u.get('member_count')==45
    cset=set(codes);ur=[]
    for m in u['members']:
        code=str(m['code']).zfill(5);present=code in cset
        ur.append({**m,'membership_asof':session,
                   'official_current_membership':'buy_sell' if present else 'absent_from_sealed_current_membership',
                   'execution_eligibility':'r0_membership_present' if present else 'not_in_sealed_current_membership',
                   'r0_membership_present':present,'formal_identity_current_session_verified':False})
    uout={**u,'schema_version':3,'effective_session':session,'universe_id':'U45_R0_SEALED_'+session,
          'members':ur,'r0_membership_verified':True,'formal_stock_universe_verified':False,
          'seal':o['seal'],'not_available_for_earlier_decisions':True}
    (out/'O_R0_UNIVERSE.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
    (out/'U_R0_UNIVERSE.json').write_text(json.dumps(uout,ensure_ascii=False,indent=2)+'\n')
    status={'schema_version':1,'target_session':session,'mode':'R0_SEALED_SAME_SESSION',
            'formal_universe_available':False,'O_r0_denominator':len(om),'U_denominator':45,
            'identity_pending_count':len(pending),'seal_id':seal.get('seal_id'),
            'source_workflow_run':seal.get('source_workflow_run'),'paid_model_calls':0,'real_orders':0}
    (out/'SNAPSHOT_STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    return status

def build(session:str,u_universe:Path,out:Path,prior_o_identity:Path|None=None,r0_seal:Path|None=None):
    if r0_seal is None:
        auto=Path('docs/runtime')/('DSA_R0_MEMBERSHIP_SEAL_'+session.replace('-','')+'.json')
        r0_seal=auto if auto.exists() else None
    if r0_seal is not None and r0_seal.exists():
        if prior_o_identity is None: raise ValueError('R0_SEAL_REQUIRES_PRIOR_IDENTITY')
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
                if not raw: raise RuntimeError('EMPTY_SOURCE')
                (src/name).write_bytes(raw)
                rows.append({'file':name,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'status':'received','bytes':len(raw)})
                break
            except Exception:
                if attempt==2: raise
                time.sleep(1+attempt)
    (src/'source-probe.json').write_text(json.dumps({'schema_version':1,'sources':rows},indent=2)+'\n')
    allowed_identity_sessions=identity_sessions_for_daily_snapshot(session)
    mode='FORMAL_IDENTITY_CURRENT_OR_PREVIOUS'
    try:
        o,u=freeze(src,session,u_universe,allowed_identity_sessions=allowed_identity_sessions)
        (out/'O_UNIVERSE.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
        (out/'U_UNIVERSE.json').write_text(json.dumps(u,ensure_ascii=False,indent=2)+'\n')
        o_r0=dict(o);o_r0['r0_membership_verified']=True
        u_r0=dict(u);u_r0['r0_membership_verified']=True
    except ValueError as exc:
        if not str(exc).startswith('HKEX_IDENTITY_DATE_UNVERIFIED:') or prior_o_identity is None:
            raise
        actual=str(exc).split(':')[1]
        if actual<=session:
            raise
        mode='R0_FUTURE_HKEX_IDENTITY_NOT_USED'
        o_r0,u_r0=freeze_r0_membership(src,session,u_universe,prior_o_identity)
        o,u=None,None
    (out/'O_R0_UNIVERSE.json').write_text(json.dumps(o_r0,ensure_ascii=False,indent=2)+'\n')
    (out/'U_R0_UNIVERSE.json').write_text(json.dumps(u_r0,ensure_ascii=False,indent=2)+'\n')
    status={'schema_version':1,'target_session':session,'mode':mode,
            'formal_universe_available':o is not None and u is not None,
            'O_r0_denominator':o_r0['member_count'],'U_denominator':45,
            'identity_pending_count':o_r0.get('identity_pending_count',0),
            'future_identity_master':o_r0.get('future_identity_master'),
            'model_calls':0,'paid_data_calls':0,'real_orders':0}
    (out/'SNAPSHOT_STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    return status
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--session',required=True);ap.add_argument('--u-universe',type=Path,required=True);ap.add_argument('--prior-o-identity',type=Path,default=Path('docs/runtime/run032_public_cache/O_UNIVERSE.json'));ap.add_argument('--r0-seal',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=False);r=build(a.session,a.u_universe,a.out,a.prior_o_identity,a.r0_seal);print(json.dumps(r))
if __name__=='__main__':main()
