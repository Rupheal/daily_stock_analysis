#!/usr/bin/env python3
"""Deterministic, sanitized DSA Dashboard feed generator. No network/model access."""
from __future__ import annotations
import argparse,json,os,re
from datetime import datetime,timezone
from pathlib import Path
BRANCH="fix/native-private-execution-20260914"
SECRET_RE=re.compile(r"(?i)(api[_-]?key|secret|token|refresh[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,}\]]+")
def load(p:Path,default=None):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except Exception:return default

def make_feed(root:Path,source_commit:str,evidence_timestamp:str|None=None)->dict:
    cap=load(root/'docs/runtime/O_FINAL_CAPTURE_005_RESULT.json',{}) or {}
    pre=load(root/'docs/runtime/O_GATE_A_PREAUTH_CHECKPOINT.json',{}) or {}
    ul=load(root/'docs/runtime/U45_PREP_LEDGER.json',{}) or {}
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    boundaries=cap.get('formal_boundaries',{})
    o_accepted=1 if boundaries.get('o_single_stock_formally_accepted') else 0
    u_accepted=int(ul.get('formal_accepted',boundaries.get('u45_formal_acceptance_added',0)) or 0)
    pre_status=pre.get('status','NOT_AVAILABLE')
    pre_g=pre.get('gates',{})
    latest_run=pre.get('run_id') if pre_status not in {'PREAUTH_CLOUD_VALIDATION_PENDING','NOT_AVAILABLE'} else cap.get('run_id')
    blocker=(pre.get('blocker') or {}).get('code') if pre_status.startswith('BLOCKED_') else (None if o_accepted else 'NEW_O_GATE_A_PROVIDER_SLOT_NOT_AUTHORIZED')
    overall='LIVE' if o_accepted else 'BLOCKED'
    stage='O_GATE_A_PREAUTH' if not o_accepted else 'O_GATE_A_ACCEPTED'
    sim='ELIGIBLE' if boundaries.get('simulated_fills',0) else 'WAIT_NOT_ELIGIBLE'
    u_summary=ul.get('summary',{})
    latest_session=(str(pre_g.get('target_session','')).replace('PASS:','') or None)
    fresh='PASS' if str(pre_g.get('fresh_preflight','')).startswith('PASS') else ('BLOCKED' if pre_status.startswith('BLOCKED_') else 'NOT_VERIFIED_FOR_NEW_GATE_A')
    prices='PASS' if str(pre_g.get('prices','')).startswith('PASS') else 'PREP_REQUIRED'
    news=pre_g.get('news','PREP_REQUIRED'); issuer=pre_g.get('issuer','PREP_REQUIRED')
    model_requests=int((pre.get('cloud_validation') or {}).get('model_requests',cap.get('resources',{}).get('new_model_requests',0)) or 0)
    cost=cap.get('resources',{}).get('model_request_cost_cny',0)
    feed={
      'meta':{'schema_version':'0.18','generated_at':now,'source_commit':source_commit,'branch':BRANCH,'latest_validated_run':latest_run,'evidence_timestamp':evidence_timestamp or pre.get('evidence_timestamp') or 'NOT_AVAILABLE'},
      'system':{'overall_state':overall,'current_stage':stage,'next_action':pre.get('next_action') or (cap.get('next_actions') or ['Continue deterministic preparation'])[-1],'last_successful_gate':'FINAL_PIPELINE_CAPTURE_ACCEPTED' if cap.get('resolution',{}).get('updated_observer_has_final_pipeline_capture') else 'NOT_VERIFIED','blocking_gate':blocker,'error_code':blocker},
      'O':{'denominator':None,'attempted':None,'succeeded':None,'failed':None,'accepted':o_accepted,'top3':[],'signal':'WAIT','qualified_buy':False,'latest_session':latest_session,'model_http_requests':model_requests,'input_tokens':0,'output_tokens':0,'total_tokens':0,'estimated_or_actual_cost':cost,'evidence_status':pre_status if pre else 'LAST_VALIDATED_NO_GO_CHILD2; NEW_GATE_A_NOT_RUN'},
      'U':{'denominator':45,'attempted':0,'succeeded':0,'failed':0,'accepted':u_accepted,'top3':[],'signal':'WAIT','qualified_buy':False,'prep_summary':u_summary or 'NOT_VERIFIED'},
      'data_health':{'fresh_preflight':fresh,'provider':prices,'session':pre_g.get('target_session','PREP_REQUIRED'),'OHLC':prices,'volume':pre_g.get('volume','CALIBRATION_AVAILABLE_RECHECK_REQUIRED'),'news':news,'issuer':issuer,'manifest':pre_g.get('manifest','PREP_REQUIRED')},
      'observer':{'pass_fail':'PASS_FINAL_CAPTURE_ENGINEERING' if cap.get('resolution',{}).get('updated_observer_has_final_pipeline_capture') else 'NOT_VERIFIED','block_count':1 if pre_status=='BLOCKED_FROZEN_NATIVE_SESSION_BOUNDARY' else 0,'latest_error_code':blocker},
      'storage':{'save':'PASS_HISTORICAL','independent_read':'PASS_HISTORICAL','sha_match':'PASS_HISTORICAL','revision_check':'PASS_HISTORICAL','restore_verified':'PASS_HISTORICAL','canonical_claim_count':1,'canonical_native_count':1},
      'budget':{'affordability':pre_g.get('affordability','NOT_VERIFIED_FOR_NEW_GATE_A'),'request_limit':int(pre.get('maximum_model_http_requests_before_owner_authorization',0) or 0),'actual_request_count':model_requests,'tokens':{'input':0,'output':0,'total':0},'cost':cost},
      'simulation':{'eligibility':sim,'account_A':'NOT_VERIFIED','account_B':'NOT_VERIFIED','cash':'NOT_VERIFIED','positions':'NOT_VERIFIED','pnl':'NOT_VERIFIED','pending_signal':'WAIT'},
      'shadow_week':{'date':now[:10],'data_pass_rate':'PARTIAL' if fresh=='PASS' and blocker else fresh,'observer_block_rate':'1 preauth boundary block' if blocker=='FROZEN_NATIVE_END_EXCLUSIVE_CURRENT_DATE' else '0','model_success_rate':'NOT_APPLICABLE_NO_MODEL_CALL' if model_requests==0 else 'NOT_VERIFIED','cost_per_accepted_analysis':'NOT_APPLICABLE' if model_requests==0 else 'NOT_VERIFIED','O_coverage':f'{o_accepted} accepted / denominator not yet frozen','U_coverage':f'{u_accepted}/45 formal accepted','top3_turnover':'NOT_VERIFIED','signal_persistence':'WAIT','BUY_WAIT':'WAIT','simulation_eligibility':sim},
      'debug':{'provider_error':None,'preflight_error':None if fresh=='PASS' else blocker,'observer_error':blocker,'drive_error':None,'model_error':'CHILD2_SEMANTIC_NO_GO_PRESERVED' if not o_accepted else None,'recovery_state':pre_status,'recovery_condition':(pre.get('blocker') or {}).get('safe_resolution') or 'Complete fresh Gate A preauth; obtain explicit owner authorization only after every hard gate passes.'}
    }
    text=json.dumps(feed,ensure_ascii=False)
    if SECRET_RE.search(text):raise SystemExit('sanitized feed failed secret scan')
    if feed['U']['denominator']!=45:raise SystemExit('U denominator invariant failed')
    if feed['budget']['actual_request_count']>feed['budget']['request_limit'] and not o_accepted:raise SystemExit('request guard invariant failed')
    return feed

def append_history(history_path:Path,feed:dict):
    history=load(history_path,{'schema_version':'0.18','append_only':True,'days':[]}) or {'schema_version':'0.18','append_only':True,'days':[]}
    days=history.setdefault('days',[]);d=feed['shadow_week'].copy();d.update(latest_validated_run=feed['meta']['latest_validated_run'],model_requests=feed['budget']['actual_request_count'],input_tokens=feed['budget']['tokens']['input'],output_tokens=feed['budget']['tokens']['output'],total_tokens=feed['budget']['tokens']['total'],cost=feed['budget']['cost'],provider_failures=feed['debug']['provider_error'],Drive_status=feed['storage']['restore_verified'],blocking_gate=feed['system']['blocking_gate'])
    existing={x.get('date') for x in days}
    if d['date'] not in existing:days.append(d)
    history_path.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--out',default='DSA_DASHBOARD_LIVE.json');ap.add_argument('--history',default='DSA_DASHBOARD_HISTORY.json');ap.add_argument('--source-commit',default=os.environ.get('GITHUB_SHA','UNKNOWN'));ap.add_argument('--evidence-timestamp');a=ap.parse_args();root=Path(a.root);feed=make_feed(root,a.source_commit,a.evidence_timestamp);Path(a.out).write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');append_history(Path(a.history),feed)
if __name__=='__main__':main()
