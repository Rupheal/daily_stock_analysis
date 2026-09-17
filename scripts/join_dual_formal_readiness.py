"""Combine verified data receipts without promoting retrieval to model acceptance."""
import argparse,hashlib,json
from pathlib import Path

def read(path):
 p=Path(path)
 return (json.loads(p.read_text()),hashlib.sha256(p.read_bytes()).hexdigest()) if p.exists() else ({},None)
def assemble(o,u,coverage,data,news,target):
 n=o.get('member_count');assert n and n==len(o['members']) and o.get('full_union_verified') is True
 assert u['member_count']==len(u['members'])==45
 cov={str(r['code']).lower().replace('hk','').zfill(5):r for r in coverage.get('coverage',[])}
 rows=[]
 for m in o['members']:
  r=cov.get(m['code'],{});ready=r.get('status')=='current_valid_bar' and r.get('latest_date')==target
  rows.append({'code':m['code'],'native_data_ready':ready,'native_model_accepted':False,'missing_reasons':([] if ready else [r.get('status','MISSING_NATIVE_DATA')])+['PER_MEMBER_INDEPENDENT_PRICE_NEWS_AND_NATIVE_OUTPUT_REQUIRED']})
 d={x['code']:x for x in data.get('members',[])};ns={x['code']:x for x in news.get('rows',[])};urs=[]
 for m in u['members']:
  code=m['code'];dr=d.get(code,{});nr=ns.get(code,{});same=data.get('target_session')==target
  reasons=[]
  if not m.get('channels'):reasons.append('ABSENT_FROM_CURRENT_OFFICIAL_BUY_LISTS')
  if not same or not dr.get('price_ready'):reasons.append('TARGET_PRICE_NOT_VERIFIED')
  if nr.get('formal_news_ready') is not True:reasons.append('NEWS_RETRIEVAL_IS_NOT_REVIEWED_EVIDENCE')
  reasons+=['INDEPENDENT_PRICE_VOLUME_RECONCILIATION_REQUIRED','CORPORATE_ACTION_SUSPENSION_AND_TRADE_PLAN_REQUIRED','U_MODEL_OUTPUT_NOT_YET_ACCEPTED']
  urs.append({'code':code,'identity_ready':m.get('identity_verified') is True,'current_buy_eligible':bool(m.get('channels')),'price_data_ready':same and dr.get('price_ready') is True,'news_retrieval_ready':nr.get('retrieval_ready') is True,'news_relevance_ready':nr.get('relevance_ready') is True,'formal_news_ready':nr.get('formal_news_ready') is True,'formal_accepted':False,'missing_reasons':reasons})
 return {'run_id':'TRI-DSA-EXEC-20260917-032','price_session':target,'membership_session':o['effective_session'],'O':{'denominator':n,'native_data_ready':sum(x['native_data_ready'] for x in rows),'native_accepted':0,'members':rows},'U':{'denominator':45,'current_buy_eligible':sum(x['current_buy_eligible'] for x in urs),'price_data_ready':sum(x['price_data_ready'] for x in urs),'news_retrieval_ready':sum(x['news_retrieval_ready'] for x in urs),'formal_accepted':0,'members':urs},'model_http_requests':0,'paid_data_calls':0,'qualified_signals':0,'authority_journal_writes':0,'historical_predictions_modified':False}
def main():
 p=argparse.ArgumentParser()
 for k in ('o-universe','u-universe','o-coverage','u-data','u-news','target','out'):p.add_argument('--'+k,required=True)
 a=p.parse_args();names=['o_universe','u_universe','o_coverage','u_data','u_news'];blobs=[read(getattr(a,k)) for k in names];r=assemble(*(x[0] for x in blobs),a.target);r['input_sha256']={k:x[1] for k,x in zip(names,blobs)};Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:({x:y for x,y in v.items() if x!='members'} if isinstance(v,dict) else v) for k,v in r.items() if k!='input_sha256'}))
if __name__=='__main__':main()
