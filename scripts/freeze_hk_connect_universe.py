"""Freeze current official Southbound stocks from complete SSE/SZSE source bytes.
No model calls. Current membership session is separate from completed price session.
"""
from __future__ import annotations
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
from openpyxl import load_workbook

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def workbook_rows(path):
 w=load_workbook(path,read_only=True,data_only=True);s=w.active;s.reset_dimensions();rows=list(s.values);w.close();return rows

def parse_hkex_identity_session(label):
 prefix='Updated as at '
 if not isinstance(label,str) or not label.startswith(prefix):raise ValueError('HKEX_IDENTITY_DATE_HEADER_INVALID')
 try:return datetime.strptime(label[len(prefix):],'%d/%m/%Y').date().isoformat()
 except ValueError as exc:raise ValueError('HKEX_IDENTITY_DATE_HEADER_INVALID') from exc

def freeze(root,session,u_path,allowed_identity_sessions=None,effective_evidence=None):
 root=Path(root);a=json.loads((root/'sse-list.json').read_text());meta=json.loads((root/'szse-list.json').read_text())[0]['metadata'];sse=a['result'];sz=workbook_rows(root/'szse-list.xlsx');hk=workbook_rows(root/'hkex-securities.xlsx')
 if len(sse)!=int(a['pageHelp']['total']) or a['pageHelp']['pageCount']!=1:raise ValueError('SSE_INCOMPLETE_PAGINATION')
 if not sse or (effective_evidence is None and {r['UPDATE_DATE'] for r in sse}!={session}):raise ValueError('SSE_SESSION_UNVERIFIED')
 if (effective_evidence is None and meta['subname']!=session) or len(sz)-1!=int(meta['recordcount']):raise ValueError('SZSE_DATE_OR_COMPLETENESS_UNVERIFIED')
 if tuple(sz[0][:3])!=('证券代码','中文简称','英文简称'):raise ValueError('SZSE_HEADER_CHANGED')
 identity_session=parse_hkex_identity_session(hk[1][0])
 allowed=set(allowed_identity_sessions or [session])
 if identity_session not in allowed:raise ValueError('HKEX_IDENTITY_DATE_UNVERIFIED:'+identity_session+':ALLOWED='+','.join(sorted(allowed)))
 if tuple(hk[2][:5])!=('Stock Code','Name of Securities','Category','Sub-Category','Board Lot'):raise ValueError('HKEX_HEADER_CHANGED')
 effective_audit=None
 if effective_evidence is not None:
  from dsa_effective_membership_v1 import reconcile
  proof=json.loads(Path(effective_evidence).read_bytes())
  if {r['UPDATE_DATE'] for r in sse}!={proof['channels']['SSE']['list_update_date']} or meta['subname']!=proof['channels']['SZSE']['list_update_date']:raise ValueError('LIST_LABEL_PROOF_MISMATCH')
  for channel,filename in [('SSE','sse-list.json'),('SZSE','szse-list.xlsx')]:
   if proof['channels'][channel]['baseline_evidence']['sha256']!=sha(root/filename):raise ValueError('BASELINE_FILE_NOT_BOUND')
  archive=(Path(effective_evidence).resolve().parent/proof['source_archive']).resolve()
  if not archive.is_relative_to(Path(effective_evidence).resolve().parent):raise ValueError('AMENDMENT_ARCHIVE_OUTSIDE_PROOF_ROOT')
  sse,sz,effective_audit=reconcile(sse,sz,archive,session,proof)
 securities={str(r[0]).zfill(5):r for r in hk[3:] if r[0] is not None}
 sbuy={r['SECURITY_CODE']:r for r in sse if r['TRADE_FLAG']=='1'}
 if any(r['TRADE_FLAG'] not in ('1','2') for r in sse):raise ValueError('UNKNOWN_TRADE_FLAG')
 zbuy={str(r[0]).zfill(5):r for r in sz[1:]}
 if len(zbuy)!=len(sz)-1 or len({r['SECURITY_CODE'] for r in sse})!=len(sse):raise ValueError('DUPLICATE_SOURCE_CODE')
 members=[];excluded=[]
 for code in sorted(set(sbuy)|set(zbuy)):
  if not re.fullmatch(r'\d{5}',code) or code not in securities:raise ValueError('SECURITY_IDENTITY_MISSING:'+code)
  h=securities[code];s=sbuy.get(code);is_stock=h[2]=='Equity' and 'Equity Securities' in str(h[3])
  if s and ((s['SECURITY_TYPE']=='股票')!=is_stock):raise ValueError('TYPE_DISAGREEMENT:'+code)
  if not is_stock:excluded.append({'code':code,'category':h[2],'sub_category':h[3]});continue
  members.append({'code':code,'official_name':(s['ABBR_CN'].strip() if s else str(zbuy[code][1]).strip()),'english_name':h[1],'security_type':'股票','channels':(['SSE'] if code in sbuy else [])+(['SZSE'] if code in zbuy else []),'board_lot':int(str(h[4]).replace(',','')),'isin':h[5],'currency':h[16]})
 sources=json.loads((root/'source-probe.json').read_text())['sources'];manifest=[{k:x[k] for k in ('file','url','sha256','started_at','completed_at')} for x in sources if x['status']=='received']
 for x in manifest:
  if sha(root/x['file'])!=x['sha256']:raise ValueError('SOURCE_HASH_CHANGED')
 if len(manifest)!=4:raise ValueError('SOURCE_TRANSPORT_INCOMPLETE')
 lookup={x['code']:x for x in members};u=json.loads(Path(u_path).read_text());assert len(u['members'])==u['member_count']==45
 ur=[]
 for m in u['members']:
  code=m['code'];h=securities.get(code);ur.append({**m,'membership_asof':session,'official_current_membership':'buy_sell' if code in lookup else 'absent_from_both_current_buy_sell_lists','execution_eligibility':('CANDIDATE_PENDING_REVIEW' if effective_audit else 'verified_current_buy_sell') if code in lookup else 'not_in_verified_current_southbound_buy_sell_union','identity_verified':bool(h),'official_name':h[1] if h else None,'board_lot':int(str(h[4]).replace(',','')) if h else None,'currency':h[16] if h else None,'channels':lookup.get(code,{}).get('channels',[])})
 now=datetime.now(timezone.utc).isoformat();common={'schema_version':2,'effective_session':session,'observed_at_utc':now,'sources':manifest,'not_available_for_earlier_decisions':True,'effective_membership_audit':effective_audit,
 'identity_master':{'source':'HKEX ListOfSecurities','asof_session':identity_session,'allowed_sessions':sorted(allowed),'same_session':identity_session==session,'membership_authority':False,
 'semantics':'Identity/category/board-lot reference only. SSE/SZSE exact-session lists remain the Southbound membership authority.'}}
 return ({**common,'universe_id':'O_SOUTHBOUND_BUY_SELL_'+session,'member_count':len(members),'full_union_verified':effective_audit is None,'candidate_union_complete':True,'members':members,'excluded_non_stocks':excluded,'sell_only_sse_codes':[r['SECURITY_CODE'] for r in sse if r['TRADE_FLAG']=='2']},{**u,**common,'members':ur})

def main():
 p=argparse.ArgumentParser();p.add_argument('--sources',required=True);p.add_argument('--session',required=True);p.add_argument('--u-universe',required=True);p.add_argument('--out',required=True);a=p.parse_args();o,u=freeze(a.sources,a.session,a.u_universe);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 for k,v in [('O_UNIVERSE',o),('U_UNIVERSE',u)]: (out/(k+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'official_O_denominator':o['member_count'],'excluded_non_stocks':len(o['excluded_non_stocks']),'U_denominator':45,'U_buy_eligible':sum(bool(x['channels']) for x in u['members']),'effective_session':a.session,'model_calls':0}))
if __name__=='__main__':main()


def freeze_r0_membership(root,session,u_path,prior_o_identity_path):
 """Exact-session SSE/SZSE membership with PIT-safe prior identity fallback.

 The currently downloaded HKEX identity master may be from a future session.
 Its rows are never consumed here. It is inspected only to record that a future
 master exists. R0 scanning is allowed; formal stock-universe acceptance is not.
 """
 root=Path(root)
 a=json.loads((root/'sse-list.json').read_text())
 meta=json.loads((root/'szse-list.json').read_text())[0]['metadata']
 sse=a['result'];sz=workbook_rows(root/'szse-list.xlsx');hk=workbook_rows(root/'hkex-securities.xlsx')
 if len(sse)!=int(a['pageHelp']['total']) or a['pageHelp']['pageCount']!=1:raise ValueError('SSE_INCOMPLETE_PAGINATION')
 if not sse or {r['UPDATE_DATE'] for r in sse}!={session}:raise ValueError('SSE_SESSION_UNVERIFIED')
 if meta['subname']!=session or len(sz)-1!=int(meta['recordcount']):raise ValueError('SZSE_DATE_OR_COMPLETENESS_UNVERIFIED')
 if tuple(sz[0][:3])!=('证券代码','中文简称','英文简称'):raise ValueError('SZSE_HEADER_CHANGED')
 identity_session=parse_hkex_identity_session(hk[1][0])
 if identity_session<=session:raise ValueError('R0_FALLBACK_REQUIRES_FUTURE_HKEX_MASTER')
 sources=json.loads((root/'source-probe.json').read_text())['sources']
 manifest=[{k:x[k] for k in ('file','url','sha256','started_at','completed_at')} for x in sources if x['status']=='received']
 for x in manifest:
  if sha(root/x['file'])!=x['sha256']:raise ValueError('SOURCE_HASH_CHANGED')
 if len(manifest)!=4:raise ValueError('SOURCE_TRANSPORT_INCOMPLETE')
 if any(r['TRADE_FLAG'] not in ('1','2') for r in sse):raise ValueError('UNKNOWN_TRADE_FLAG')
 sbuy={str(r['SECURITY_CODE']).zfill(5):r for r in sse if r['TRADE_FLAG']=='1'}
 zbuy={str(r[0]).zfill(5):r for r in sz[1:]}
 if len(zbuy)!=len(sz)-1 or len({str(r['SECURITY_CODE']).zfill(5) for r in sse})!=len(sse):raise ValueError('DUPLICATE_SOURCE_CODE')
 prior=json.loads(Path(prior_o_identity_path).read_text())
 prior_map={str(x['code']).zfill(5):x for x in prior.get('members') or []}
 raw_codes=sorted(set(sbuy)|set(zbuy))
 members=[];known_nonstock=[];identity_pending=[]
 for code in raw_codes:
  s=sbuy.get(code);z=zbuy.get(code);p=prior_map.get(code)
  channels=(['SSE'] if s else [])+(['SZSE'] if z else [])
  if s and s.get('SECURITY_TYPE')!='股票':
   known_nonstock.append({'code':code,'security_type':s.get('SECURITY_TYPE'),'channels':channels});continue
  if p and p.get('security_type')=='股票':
   status='PIT_PRIOR_IDENTITY'
   sec='股票';english=p.get('english_name');board=p.get('board_lot');isin=p.get('isin');currency=p.get('currency')
  elif s and s.get('SECURITY_TYPE')=='股票':
   status='SSE_EXACT_SESSION_STOCK_HKEX_FIELDS_PENDING'
   sec='股票';english=None;board=None;isin=None;currency=None
   identity_pending.append(code)
  else:
   status='IDENTITY_PENDING_SZSE_ONLY'
   sec='UNRESOLVED';english=None;board=None;isin=None;currency=None
   identity_pending.append(code)
  name=(str(s.get('ABBR_CN') or '').strip() if s else str((z or [None,''])[1] or '').strip())
  members.append({'code':code,'official_name':name,'english_name':english,'security_type':sec,'channels':channels,
                  'board_lot':board,'isin':isin,'currency':currency,'identity_status':status,
                  'identity_source_asof':prior.get('effective_session') if p else None,
                  'formal_identity_current_session_verified':False})
 u=json.loads(Path(u_path).read_text());assert len(u['members'])==u['member_count']==45
 ur=[]
 for m in u['members']:
  code=str(m['code']).zfill(5);p=prior_map.get(code);channels=(['SSE'] if code in sbuy else [])+(['SZSE'] if code in zbuy else [])
  ur.append({**m,'membership_asof':session,'official_current_membership':'buy_sell' if channels else 'absent_from_both_current_buy_sell_lists',
             'execution_eligibility':'verified_current_buy_sell' if channels else 'not_in_verified_current_southbound_buy_sell_union',
             'channels':channels,'identity_source_asof':prior.get('effective_session') if p else m.get('membership_asof'),
             'formal_identity_current_session_verified':False})
 now=datetime.now(timezone.utc).isoformat()
 common={'schema_version':3,'effective_session':session,'observed_at_utc':now,'sources':manifest,
         'r0_membership_verified':True,'formal_stock_universe_verified':False,
         'future_identity_master':{'source':'HKEX ListOfSecurities','asof_session':identity_session,'used':False},
         'identity_fallback':{'source_path':str(prior_o_identity_path),'asof_session':prior.get('effective_session'),
                              'purpose':'R0 identity enrichment only; not current-session formal identity Authority'},
         'not_available_for_earlier_decisions':True}
 o={**common,'universe_id':'O_R0_SOUTHBOUND_MEMBERSHIP_'+session,'member_count':len(members),'members':members,
    'raw_membership_denominator':len(raw_codes),'known_nonstock_excluded':known_nonstock,
    'identity_pending_codes':identity_pending,'identity_pending_count':len(identity_pending),
    'sell_only_sse_codes':[str(r['SECURITY_CODE']).zfill(5) for r in sse if r['TRADE_FLAG']=='2']}
 return o,{**u,**common,'universe_id':'U45_R0_'+session,'members':ur}
