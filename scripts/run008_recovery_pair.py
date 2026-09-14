"""New paired research freeze. Reuse accepted scorer; never edit Run005 outputs."""
import argparse
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from scripts import run004_pool_safe_deepseek as base
from src.services.dsa_prediction_ledger import canonical_hash,freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope


def now():return datetime.now(timezone.utc).isoformat()
def dt(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
def write(path,x):
    with Path(path).open('x') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False)
def load(path):return json.loads(Path(path).read_text())


def prepare(recovery,universe,contract):
    members=[x['code'] for x in universe['members']]
    if len(set(members))!=len(members) or len(members)!=universe['member_count'] or not universe['full_union_verified']:
        raise ValueError('universe_integrity')
    if recovery['as_of']!=contract['data_as_of'] or recovery['feature_input_sha256']!=contract['recovery_feature_input_sha256']:
        raise ValueError('recovery_lineage')
    by={r['code']:r for r in recovery['rows']};missing={r['code']:r['reason'] for r in recovery['retained']}
    for r in by.values():
        if canonical_hash(r['features'])!=r['feature_sha256']:raise ValueError('feature_hash')
    candidates=[];isolated=[]
    for code in members:
        if code in missing:isolated.append({'code':code,'reason':missing[code]});continue
        if code not in by:isolated.append({'code':code,'reason':'NEW_CODE_HISTORY_NOT_VERIFIED'});continue
        candidates.append(by[code])
    return members,candidates,isolated


def balance(key):
    req=Request('https://api.deepseek.com/user/balance',headers={'Authorization':'Bearer '+key})
    with urlopen(req,timeout=20) as r:x=json.load(r)
    if not x.get('is_available'):raise ValueError('balance_unavailable')
    for row in x.get('balance_infos',[]):
        if row.get('currency')=='CNY':return max(0,float(row['total_balance']))
    raise ValueError('CNY_balance_not_verified')


def execute(args):
    c=load(args.contract);u=load(args.universe);r=load(args.recovery)
    members,candidates,isolated=prepare(r,u,c)
    if dt(now())>=dt(c['input_admission_deadline']):raise ValueError('input_cutoff_missed_no_calls')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    initial={'run_id':c['run_id'],'frozen_at':now(),'contract_sha256':canonical_hash(c),'universe_sha256':canonical_hash(u),
             'recovery_file_sha256':base.file_sha256(args.recovery),'candidate_input_sha256':canonical_hash(candidates),
             'denominator':len(members),'feature_ready':len(candidates),'isolated':isolated,'outcome_read':False}
    write(out/'input-freeze.json',initial)
    if args.preflight:
        print(json.dumps({'preflight':True,'denominator':len(members),'feature_ready':len(candidates),'isolated':len(isolated)}));return
    key=os.environ['DEEPSEEK_API_KEY'];available=balance(key);limit=min(c['max_cny'],available)
    lock=threading.Lock();spent=0.;requests=0;reserve_inflight=0.;responses={v:[] for v in c['variants']};failures={v:list(isolated) for v in c['variants']}
    def one(job):
        nonlocal spent,requests,reserve_inflight
        variant,row=job;code=row['code'];facts={k:v for k,v in row['features'].items() if k not in c['variants'][variant]}
        body=base.request_object(c['model'],facts);reserve=base.conservative_request_reserve_cny(body)
        with lock:
            if dt(now())>=dt(c['freeze_deadline']):reason='freeze_deadline'
            elif requests>=c['max_requests']:reason='request_cap'
            elif spent+reserve_inflight+reserve>limit:reason='budget_cap'
            else:reason=None;requests+=1;reserve_inflight+=reserve
        if reason:return variant,{'code':code,'reason':reason},False
        try:
            raw=base._post_json(base.API_URL,body,key,timeout=35)
            result,model,usage=base.parse_provider_response(raw)
            cost=base.usage_peak_cost_cny(usage) or reserve
            safe={'code':code,**result,'feature_sha256':canonical_hash(facts),'model':model,'usage':{k:int(usage.get(k) or 0) for k in ('prompt_tokens','completion_tokens','total_tokens')},'peak_cost_estimate_cny':cost,'completed_at':now()}
            safe['result_sha256']=canonical_hash(safe)
            ok=True
        except Exception as e:
            cost=reserve;safe={'code':code,'reason':'model_failure:'+type(e).__name__};ok=False
        with lock:reserve_inflight-=reserve;spent+=cost
        return variant,safe,ok
    # Interleave pairs so interrupted budget does not favor one variant first.
    jobs=[(v,row) for row in candidates for v in c['variants']]
    with ThreadPoolExecutor(max_workers=c['max_workers']) as pool:
        for v,row,ok in pool.map(one,jobs):
            (responses[v] if ok else failures[v]).append(row)
            # Crash checkpoint contains only sanitized enums and usage, never raw text/key.
            with (out/'completed-requests.jsonl').open('a') as f:f.write(json.dumps({'variant':v,'ok':ok,'record':row})+'\n');f.flush();os.fsync(f.fileno())
    ended=now();on_time=dt(ended)<dt(c['freeze_deadline']);manifests=[]
    for variant in c['variants']:
        ranked=[dict(row,rank=i+1) for i,row in enumerate(sorted(responses[variant],key=lambda x:(-x['score'],x['code'])))];failed=sorted(failures[variant],key=lambda x:x['code'])
        env=build_ranking_envelope(members,ranked,failed,as_of=initial['frozen_at'])
        variant_facts=[{'code':x['code'],'features':{k:v for k,v in x['features'].items() if k not in c['variants'][variant]}} for x in candidates]
        ranking_hash=canonical_hash(ranked)
        payload={'run_id':c['run_id']+'-'+variant,'snapshot_id':c['run_id']+'-'+variant,'variant':variant,'scope':c['scope'],
                 'generated_at':ended,'decision_cutoff':initial['frozen_at'],'data_as_of':c['data_as_of'],'outcome_not_before':c['outcome_reference_not_before'],
                 'status':'FROZEN_PRE_OUTCOME' if on_time else 'MISSED_FREEZE_DEADLINE_NOT_VALID_OOS',
                 'denominator':len(members),'ranked_count':len(ranked),'isolated_count':len(failed),'ranked':ranked,'isolated':failed,
                 'top3':ranked[:3],'top10':ranked[:10],'ranking_sha256':ranking_hash,'input_sha256':canonical_hash(variant_facts),
                 'model_requested':c['model'],'models_returned':sorted({x['model'] for x in ranked}),'contract_sha256':canonical_hash(c),
                 'universe_sha256':canonical_hash(u),'ranking_envelope':env,'old_run005_mutated':False,'production_authority':False,'shadow_entry_authority':False}
        write(out/(variant+'-snapshot.json'),payload)
        if on_time:
            freeze_prediction(out/'predictions',{'run_id':payload['run_id'],'generated_at':ended,'as_of':c['data_as_of']+'T16:00:00+08:00',
               'universe_sha256':canonical_hash(u),'input_sha256':payload['input_sha256'],'model_version':c['model'],'config_sha256':canonical_hash(c),
               'prediction_payload_sha256':canonical_hash(payload),'ranking_sha256':ranking_hash,'status':'PRE_OUTCOME_RESEARCH_ONLY'})
        manifests.append({k:payload[k] for k in ('run_id','variant','status','denominator','ranked_count','isolated_count','ranking_sha256','input_sha256','generated_at')})
    cost={'model_http_requests':requests,'peak_estimate_cny':round(spent,8),'actual_invoice_cny':None,'budget_cap_cny':c['max_cny'],'verified_balance_sufficient_at_start':available>=c['max_cny'],'auto_recharge':False,'rate_basis':'conservative prior peak 3/9 CNY per million input/output >= official Flash peak 2/8; cache discounts not assumed','pricing_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'}
    write(out/'cost.json',cost);write(out/'manifest.json',{'run_id':c['run_id'],'variants':manifests,'cost':cost,'input_freeze_sha256':canonical_hash(initial),'old_run005_mutated':False,'feature_ready':len(candidates),'predictions_are_original_native_dsa':False})
    print('RUN008_FROZEN',json.dumps({'variants':manifests,'cost':cost}))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('contract','universe','recovery','output'):p.add_argument('--'+k,required=True)
    p.add_argument('--preflight',action='store_true');execute(p.parse_args())
