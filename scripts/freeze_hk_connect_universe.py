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

def freeze(root,session,u_path,allowed_identity_sessions=None):
 root=Path(root);a=json.loads((root/'sse-list.json').read_text());meta=json.loads((root/'szse-list.json').read_text())[0]['metadata'];sse=a['result'];sz=workbook_rows(root/'szse-list.xlsx');hk=workbook_rows(root/'hkex-securities.xlsx')
 if len(sse)!=int(a['pageHelp']['total']) or a['pageHelp']['pageCount']!=1:raise ValueError('SSE_INCOMPLETE_PAGINATION')
 if not sse or {r['UPDATE_DATE'] for r in sse}!={session}:raise ValueError('SSE_SESSION_UNVERIFIED')
 if meta['subname']!=session or len(sz)-1!=int(meta['recordcount']):raise ValueError('SZSE_DATE_OR_COMPLETENESS_UNVERIFIED')
 if tuple(sz[0][:3])!=('证券代码','中文简称','英文简称'):raise ValueError('SZSE_HEADER_CHANGED')
 identity_session=parse_hkex_identity_session(hk[1][0])
 allowed=set(allowed_identity_sessions or [session])
 if identity_session not in allowed:raise ValueError('HKEX_IDENTITY_DATE_UNVERIFIED')
 if tuple(hk[2][:5])!=('Stock Code','Name of Securities','Category','Sub-Category','Board Lot'):raise ValueError('HKEX_HEADER_CHANGED')
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
  code=m['code'];h=securities.get(code);ur.append({**m,'membership_asof':session,'official_current_membership':'buy_sell' if code in lookup else 'absent_from_both_current_buy_sell_lists','execution_eligibility':'verified_current_buy_sell' if code in lookup else 'not_in_verified_current_southbound_buy_sell_union','identity_verified':bool(h),'official_name':h[1] if h else None,'board_lot':int(str(h[4]).replace(',','')) if h else None,'currency':h[16] if h else None,'channels':lookup.get(code,{}).get('channels',[])})
 now=datetime.now(timezone.utc).isoformat();common={'schema_version':2,'effective_session':session,'observed_at_utc':now,'sources':manifest,'not_available_for_earlier_decisions':True,
 'identity_master':{'source':'HKEX ListOfSecurities','asof_session':identity_session,'allowed_sessions':sorted(allowed),'same_session':identity_session==session,'membership_authority':False,
 'semantics':'Identity/category/board-lot reference only. SSE/SZSE exact-session lists remain the Southbound membership authority.'}}
 return ({**common,'universe_id':'O_SOUTHBOUND_BUY_SELL_'+session,'member_count':len(members),'full_union_verified':True,'members':members,'excluded_non_stocks':excluded,'sell_only_sse_codes':[r['SECURITY_CODE'] for r in sse if r['TRADE_FLAG']=='2']},{**u,**common,'members':ur})

def main():
 p=argparse.ArgumentParser();p.add_argument('--sources',required=True);p.add_argument('--session',required=True);p.add_argument('--u-universe',required=True);p.add_argument('--out',required=True);a=p.parse_args();o,u=freeze(a.sources,a.session,a.u_universe);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 for k,v in [('O_UNIVERSE',o),('U_UNIVERSE',u)]: (out/(k+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'official_O_denominator':o['member_count'],'excluded_non_stocks':len(o['excluded_non_stocks']),'U_denominator':45,'U_buy_eligible':sum(bool(x['channels']) for x in u['members']),'effective_session':a.session,'model_calls':0}))
if __name__=='__main__':main()
