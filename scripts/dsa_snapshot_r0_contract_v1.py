"""Separate exact-date formal identity from a source-verified R0 member seal."""
from __future__ import annotations
import hashlib,json,re
from datetime import date

def validate_seal(seal,target,coverage=None):
    date.fromisoformat(target)
    if seal.get('status')!='ACCEPTED_SAME_SESSION_R0_MEMBERSHIP_SEAL' or seal.get('target_session')!=target:raise ValueError('R0_MEMBERSHIP_SEAL_IDENTITY_INVALID')
    codes=seal.get('codes') or []
    if not codes or any(not isinstance(c,str) or not re.fullmatch(r'[0-9]{5}',c) for c in codes):raise ValueError('R0_MEMBERSHIP_SEAL_CODE_INVALID')
    if len(codes)!=seal.get('membership_code_count') or len(codes)!=len(set(codes)):raise ValueError('R0_MEMBERSHIP_SEAL_DENOMINATOR_INVALID')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',str(seal.get('source_artifact_digest',''))):raise ValueError('R0_SEAL_ARTIFACT_DIGEST_INVALID')
    if not re.fullmatch(r'[0-9a-f]{64}',str(seal.get('source_universe_sha256',''))):raise ValueError('R0_SEAL_UNIVERSE_HASH_INVALID')
    if not re.fullmatch(r'[0-9a-f]{40}',str(seal.get('source_head_sha',''))):raise ValueError('R0_SEAL_SOURCE_COMMIT_INVALID')
    if coverage is not None:
        if coverage.get('expected_complete_session')!=target or coverage.get('decision_session')!=target:raise ValueError('R0_SEAL_SOURCE_SESSION_MISMATCH')
        requested=[str(c).lower().removeprefix('hk').zfill(5) for c in coverage.get('requested_codes',[])]
        if requested!=codes or coverage.get('coverage_denominator')!=len(codes):raise ValueError('R0_SEAL_SOURCE_CODES_MISMATCH')
        if coverage.get('universe_sha256')!=seal['source_universe_sha256']:raise ValueError('R0_SEAL_SOURCE_UNIVERSE_HASH_MISMATCH')
        if coverage.get('model_credentials_provided') is not False or coverage.get('model_analysis_enabled') is not False:raise ValueError('R0_SEAL_SOURCE_MODEL_BOUNDARY')
    return codes

def materialize_r0(session,u_path,prior_path,seal_path,out):
    seal=json.loads(seal_path.read_text());codes=validate_seal(seal,session)
    prior=json.loads(prior_path.read_text());asof=prior.get('effective_session')
    if not isinstance(asof,str):raise ValueError('R0_PRIOR_IDENTITY_DATE_MISSING')
    if date.fromisoformat(asof)>date.fromisoformat(session):raise ValueError('R0_PRIOR_IDENTITY_IS_FUTURE')
    pm=prior.get('members') or [];pmap={str(x.get('code','')).zfill(5):x for x in pm}
    if len(pmap)!=len(pm):raise ValueError('R0_PRIOR_IDENTITY_DUPLICATE')
    members=[];pending=[]
    for c in codes:
        old=pmap.get(c)
        if old is None:pending.append(c)
        members.append({'code':c,'official_name':(old or {}).get('official_name') or c,'security_type':(old or {}).get('security_type') or 'UNRESOLVED','identity_source_asof':asof if old else None,'identity_status':'PIT_PRIOR_IDENTITY_REFERENCE_ONLY' if old else 'SEALED_MEMBERSHIP_IDENTITY_PENDING','board_lot':None,'isin':None,'currency':None,'channels':[],'formal_identity_current_session_verified':False})
    provenance={k:seal[k] for k in ('seal_id','source_workflow_run','source_artifact_id','source_artifact_digest','source_head_sha','source_universe_sha256')}
    provenance['seal_file_sha256']=hashlib.sha256(seal_path.read_bytes()).hexdigest()
    common={'schema_version':3,'effective_session':session,'r0_membership_verified':True,'formal_stock_universe_verified':False,'full_union_verified':False,'seal':provenance,'not_available_for_earlier_decisions':True}
    o={**common,'universe_id':'O_R0_SEALED_'+session,'member_count':len(codes),'members':members,'identity_pending_codes':pending,'identity_pending_count':len(pending)}
    source_u=json.loads(u_path.read_text());ur=source_u.get('members') or [];uc=[str(m.get('code','')).zfill(5) for m in ur]
    if len(uc)!=45 or len(set(uc))!=45:raise ValueError('U45_MEMBER_SET_INVALID')
    us=[];cset=set(codes)
    for m,c in zip(ur,uc):us.append({**m,'code':c,'membership_asof':session,'identity_verified':False,'formal_identity_current_session_verified':False,'board_lot':None,'isin':None,'currency':None,'r0_membership_present':c in cset,'execution_eligibility':'R0_ONLY_NOT_EXECUTION_ELIGIBILITY'})
    u={**source_u,**common,'universe_id':'U45_R0_SEALED_'+session,'members':us}
    out.mkdir(parents=True,exist_ok=True)
    for name,obj in [('O_R0_UNIVERSE',o),('U_R0_UNIVERSE',u)]:(out/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    status={'schema_version':2,'target_session':session,'mode':'R0_SEALED_SAME_SESSION','formal_universe_available':False,'O_r0_denominator':len(codes),'U_denominator':45,'identity_pending_count':len(pending),'identity_pending_codes':pending,'seal_id':seal['seal_id'],'paid_model_calls':0,'real_orders':0}
    (out/'SNAPSHOT_STATUS.json').write_text(json.dumps(status,indent=2)+'\n');return status
