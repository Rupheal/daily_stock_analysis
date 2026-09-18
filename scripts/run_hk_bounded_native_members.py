"""Two new evidence-bound native members; private originals and no signal publish.

No reuse of closed Gate-A request slots. Free failure gates precede every claim.
"""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from dsa_drive_store import DriveStore,scoped_token,StoreError
from dsa_drive_bundle import bundle,verify_bundle
from o_release_quote_semantics import build_release_view
from o_release_gate_contract import evaluate_release_gate


def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def balance():
    with httpx.Client(timeout=20) as c:
        r=c.get('https://api.deepseek.com/user/balance',headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']});r.raise_for_status();d=r.json()
    rows=[x for x in d.get('balance_infos',[]) if x['currency']=='CNY']
    if not d.get('is_available') or len(rows)!=1:raise ValueError('AVAILABLE_CNY_BALANCE_UNVERIFIED')
    return Decimal(rows[0]['total_balance'])


def command(script,args,env,log):
    with log.open('w') as handle:
        return subprocess.run([sys.executable,str(script),*args],env=env,stdout=handle,stderr=subprocess.STDOUT,timeout=600).returncode


def private_save(root,artifact_id,run_id):
    from dsa_private_multipart import save
    with httpx.Client(timeout=30,follow_redirects=False) as c:
        c.headers['Authorization']='Bearer '+scoped_token(c);s=DriveStore(c,os.environ['DSA_DRIVE_FOLDER_ID'])
        return save(root,artifact_id,run_id,s)


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkout',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--scope',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();s=json.loads(a.scope.read_text());a.out.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1];scripts=repo/'scripts';universe=repo/'docs/runtime/run032_public_cache/O_UNIVERSE.json';codes=s['codes']
    assert s['maximum_requests']==len(codes)==len(set(codes)) and 1<=len(codes)<=2 and Decimal(s['maximum_cost_cny'])==Decimal('0.10')*len(codes) and s['per_member_cap_cny']=='0.10'
    assert hashlib.sha256(a.cache.read_bytes()).hexdigest()==s['history_cache_sha256']
    assert os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_EVENT_NAME')=='push'
    from o_target_session_contract import resolve_target_session
    assert resolve_target_session(datetime.now(timezone.utc)).target_session.isoformat()==s['target_session']
    rows=[];reserved=Decimal('0');stop=False
    safe_env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ('SECRET','TOKEN','API_KEY','WEBHOOK','DSA_DRIVE'))}
    for code in codes:
        row={'code':code,'status':'PENDING','model_http_requests_confirmed':0,'model_http_requests_possible':0,'qualified_signal':False,'private_persistence':None};root=a.out/code;root.mkdir();artifact=s['artifact_prefix']+'-'+code;run_id=s['run_id']+'-'+code
        if stop:row['status']='ISOLATED_AFTER_PRIVATE_OR_SHARED_FAILURE';rows.append(row);continue
        try:
            pre=root/'preflight'
            if s.get('preflight_contract')=='POOL_TARGET_V2':
                plan=repo/(s.get('preflight_plan') or 'docs/runtime/RUN057_O_NATIVE_PLAN.json')
                preflight_script=scripts/'prepare_hk_pool_rollout_preflight_v2.py'
                preflight_args=['--code',code,'--target',s['target_session'],'--universe',str(universe),'--cache',str(a.cache.resolve()),'--plan',str(plan.resolve()),'--out',str(pre)]
            else:
                preflight_script=scripts/'prepare_hk_member_acceptance.py'
                preflight_args=['--code',code,'--target',s['target_session'],'--universe',str(universe),'--cache',str(a.cache.resolve()),'--out',str(pre)]
            rc=command(preflight_script,preflight_args,safe_env,root/'preflight.stdout')
            if rc or not (pre/'preflight.json').exists():
                detail=json.loads((pre/'FREE_PREFLIGHT_STATUS.json').read_text()).get('reason','') if (pre/'FREE_PREFLIGHT_STATUS.json').exists() else ''
                raise ValueError('FREE_PREFLIGHT_FAILED:'+detail)
            common=['--symbol','HK'+code,'--checkout',str(a.checkout.resolve()),'--expected-commit',s['frozen_upstream'],'--preflight',str(pre/'preflight.json'),'--limit-cny','0.10','--carry-upper-cny','0','--target-boundary-adapter','--news-handoff-v1']
            if s.get('frozen_native_history_adapter'):
                common.append('--frozen-native-history-adapter')
                row['frozen_native_history_adapter']=True
            if s.get('news_coverage_limitation_v1'):
                common.append('--news-coverage-limitation-v1')
                row['news_coverage_limitation_v1']=True
            env=dict(safe_env,DSA_DEEPSEEK_V41_TOKENIZER=os.environ['DSA_DEEPSEEK_V41_TOKENIZER'],LLM_CHANNELS='deepseek',LLM_DEEPSEEK_PROTOCOL='openai',LLM_DEEPSEEK_BASE_URL='https://api.deepseek.com',LLM_DEEPSEEK_MODELS='deepseek-flash',LITELLM_MODEL='openai/deepseek-flash',LITELLM_FALLBACK_MODELS='',REPORT_INTEGRITY_RETRY='0',MAX_WORKERS='1',DSA_INPUT_TOKEN_MARGIN='2048')
            if s.get('native_model_configuration'):
                from o_native_model_configuration import configure
                env.update(configure(root, s['native_model_configuration']))
                row['native_model_configuration']=s['native_model_configuration']
            dry=root/'dry';env.update(DSA_BUDGET_PROBE_ONLY='1',LLM_DEEPSEEK_API_KEY='dry-envelope-no-network')
            command(scripts/'run_hk_original_model_probe_run030.py',[*common,'--output',str(dry)],env,root/'dry.stdout')
            budget=json.loads((dry/'budget.json').read_text());req=budget.get('requests') or []
            if len(req)!=1 or req[0]['status']!='dry_envelope_validated_not_sent':raise ValueError('FREE_NATIVE_ENVELOPE_FAILED')
            upper=Decimal(req[0]['pre_send_peak_upper_cny']);assert upper<=Decimal('0.10')
            row['pre_send_upper_cny']=str(upper);row['preflight_sha256']=hashlib.sha256((pre/'preflight.json').read_bytes()).hexdigest()
            row['pre_send_private_persistence']=private_save(root,artifact+'-PRE-SEND',run_id)
            if not row['pre_send_private_persistence'].get('save_read_hash_restore'):raise ValueError('PRE_SEND_PRIVATE_SAVE_UNVERIFIED')
            if s.get('model_free_storage_probe'):
                row['status']='FREE_NATIVE_ENVELOPE_AND_PRIVATE_STORAGE_PASS';continue
            before=balance();write(root/'private-balance-before.json',{'currency':'CNY','available_balance':str(before),'retrieved_at':datetime.now(timezone.utc).isoformat()})
            if before<Decimal('0.10') or reserved+Decimal('0.10')>Decimal(s['maximum_cost_cny']):raise ValueError('BUDGET_OR_BALANCE_INSUFFICIENT')
            with httpx.Client(timeout=30,follow_redirects=False) as c:
                c.headers['Authorization']='Bearer '+scoped_token(c);store=DriveStore(c,os.environ['DSA_DRIVE_FOLDER_ID']);claim=store.reserve_native_call(artifact,run_id,row['preflight_sha256'],'CI-'+os.environ['GITHUB_RUN_ID']+'-'+code)
            write(root/'private-claim.json',claim);row['claim_persisted']=True;reserved+=Decimal('0.10')
            actual=root/'native';env.update(DSA_BUDGET_PROBE_ONLY='0',LLM_DEEPSEEK_API_KEY=os.environ['DEEPSEEK_API_KEY'])
            rc=command(scripts/'run_hk_original_model_probe_run030.py',[*common,'--output',str(actual)],env,root/'native.stdout');row['native_exit_code']=rc
            b=json.loads((actual/'budget.json').read_text());requests=b.get('requests') or []
            row['model_http_requests_possible']=len(requests);row['model_http_requests_confirmed']=sum(r.get('status')=='response_received' for r in requests)
            row['usage_peak_estimate_cny']=str(sum(Decimal(r.get('usage_peak_estimate_cny',r['charge_upper_cny'])) for r in requests));row['usage']=[r.get('usage') for r in requests]
            try:
                after=balance();write(root/'private-balance-after.json',{'currency':'CNY','available_balance':str(after),'retrieved_at':datetime.now(timezone.utc).isoformat()});row['observed_balance_change_cny']=str(before-after)
            except Exception:row['observed_balance_change_cny']=None
            row['actual_attributable_charge_cny']=None
            from o_provider_completion import inspect_completion
            completion=inspect_completion((actual/'provider-response.txt').read_bytes())
            write(actual/'provider-completion-audit.json',completion);row['provider_completion']=completion
            if completion['status']!='PASS':raise ValueError('|'.join(completion['blockers']))
            post=json.loads((actual/'post-output-contract.json').read_text());gate=post.get('promotion_gate') or {};row['raw_blockers']=gate.get('blockers',[]);row['raw_gate']=gate.get('status')
            if gate.get('status')=='PASS':row['status']='PASS_NATIVE_AUTOMATED_PENDING_MANUAL_REVIEW'
            elif set(row['raw_blockers'])=={'SEM-001'}:
                preflight=json.loads((pre/'preflight.json').read_text());inp=json.loads((actual/'original-input.json').read_text());raw=json.loads((actual/'pipeline-final-result.json').read_text());b=build_release_view(preflight,inp,raw);g=evaluate_release_gate(post,b)
                write(root/'release-view.json',b);write(root/'release-gate.json',g);row['status']=g['status']+'_PENDING_MANUAL_REVIEW';row['release_strategy_fields_changed']=b['receipt']['strategy_fields_changed']
            else:row['status']='NATIVE_OUTPUT_ISOLATED';stop=True
        except Exception as exc:
            row['status']='ISOLATED';row['failure_class']=type(exc).__name__;row['failure_code']=str(exc)[:140] if isinstance(exc,(ValueError,AssertionError)) else type(exc).__name__
            # Any durable claim means a send may have occurred even when downstream receipts are missing.
            if row.get('claim_persisted'):
                actual=root/'native'/'budget.json'
                if actual.exists():
                    b=json.loads(actual.read_text());q=b.get('requests') or [];row['model_http_requests_possible']=len(q);row['model_http_requests_confirmed']=sum(x.get('status')=='response_received' for x in q);row['usage_peak_estimate_cny']=str(sum(Decimal(x.get('usage_peak_estimate_cny',x['charge_upper_cny'])) for x in q))
                else:row['model_http_requests_possible']=1
                stop=True
        finally:
            try:
                write(root/'member-summary.json',row);row['private_persistence']=private_save(root,artifact,run_id)
                if not row['private_persistence']['save_read_hash_restore']:stop=True
            except Exception as exc:
                reason=str(exc) if isinstance(exc,StoreError) and str(exc).replace('_','').isalnum() else type(exc).__name__
                row['private_persistence']={'status':'FAIL','reason':reason};stop=True
            rows.append(row);write(a.out/'SANITIZED_RESULT.json',{'run_id':s['run_id'],'workflow_run':os.environ.get('GITHUB_RUN_ID'),'O_denominator':660,'attempted_members':len(rows),'members':rows,'model_http_requests_confirmed':sum(x['model_http_requests_confirmed'] for x in rows),'model_http_requests_possible':sum(x['model_http_requests_possible'] for x in rows),'maximum_cost_cny':s['maximum_cost_cny'],'actual_attributable_charge_cny':None,'qualified_signals':0,'formal_pool_top3_generated':False,'simulation_ledger_writes':0,'manual_review_required':True})
            print('BOUNDED_NATIVE_MEMBER '+json.dumps(row,ensure_ascii=False),flush=True)
    write(a.out/'SANITIZED_RESULT.json',{'run_id':s['run_id'],'workflow_run':os.environ.get('GITHUB_RUN_ID'),'O_denominator':660,'attempted_members':len(rows),'members':rows,'model_http_requests_confirmed':sum(x['model_http_requests_confirmed'] for x in rows),'model_http_requests_possible':sum(x['model_http_requests_possible'] for x in rows),'maximum_cost_cny':s['maximum_cost_cny'],'actual_attributable_charge_cny':None,'qualified_signals':0,'formal_pool_top3_generated':False,'simulation_ledger_writes':0,'manual_review_required':True})
if __name__=='__main__':main()
