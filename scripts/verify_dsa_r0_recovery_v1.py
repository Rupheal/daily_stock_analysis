"""Read-only R0 audit. GitHub credential is restricted to artifact reads."""
from __future__ import annotations
import argparse,hashlib,io,json,os,subprocess,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from dsa_snapshot_r0_contract_v1 import validate_seal
from dsa_daily_market_snapshot_v1 import build_from_r0_seal
ROOT=Path(__file__).resolve().parents[1]
API='https://api.github.com/repos/Rupheal/daily_stock_analysis'
O_RUN=35612350424;O_ART=10644099371
O_DIGEST='sha256:57eb85d79d52a4334161e4d4ae57eb0191a5141c6cb1a40ee3d439ed58df6c10'
def api(path):
    r=requests.get(API+path,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'},timeout=40)
    r.raise_for_status();return r.json()
def archive(aid,digest,rid,head=None):
    meta=api('/actions/artifacts/'+str(aid))
    if meta.get('expired') or meta.get('digest')!=digest or meta.get('workflow_run',{}).get('id')!=rid:raise ValueError('ARTIFACT_METADATA_MISMATCH')
    run=api('/actions/runs/'+str(rid))
    if run.get('status')!='completed' or run.get('conclusion')!='success':raise ValueError('SOURCE_RUN_NOT_SUCCESS')
    if head is not None and run.get('head_sha')!=head:raise ValueError('SOURCE_HEAD_MISMATCH')
    r=requests.get(API+'/actions/artifacts/'+str(aid)+'/zip',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN']},allow_redirects=False,timeout=40)
    if r.status_code in (301,302,303,307,308):
        url=r.headers['Location'];parsed=urlparse(url)
        if parsed.scheme!='https' or not any((parsed.hostname or '').endswith(x) for x in ('.blob.core.windows.net','.githubusercontent.com')):raise ValueError('ARTIFACT_STORAGE_ORIGIN_UNVERIFIED')
        r=requests.get(url,timeout=60)
    r.raise_for_status();raw=r.content
    if len(raw)>50000000 or 'sha256:'+hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('ARTIFACT_BYTES_HASH_MISMATCH')
    z=zipfile.ZipFile(io.BytesIO(raw))
    if sum(x.file_size for x in z.infolist())>100000000:raise ValueError('ARTIFACT_EXPANDED_SIZE_LIMIT')
    return z,run
def read_one(z,suffix):
    names=[n for n in z.namelist() if n==suffix or n.endswith('/'+suffix)]
    if len(names)!=1:raise ValueError('ARTIFACT_MEMBER_AMBIGUOUS:'+suffix)
    raw=z.read(names[0]);return json.loads(raw),hashlib.sha256(raw).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    target='2026-09-21';sp=ROOT/'docs/runtime/DSA_R0_MEMBERSHIP_SEAL_20260921.json';seal=json.loads(sp.read_text())
    original,_=archive(seal['source_artifact_id'],seal['source_artifact_digest'],seal['source_workflow_run'],seal['source_head_sha'])
    cov,covhash=read_one(original,'coverage.json');codes=validate_seal(seal,target,cov)
    current,orun=archive(O_ART,O_DIGEST,O_RUN);oc,ochash=read_one(current,'coverage.json')
    actual=[str(x['code']).lower().removeprefix('hk').zfill(5) for x in oc.get('coverage',[])]
    requested=[str(x).lower().removeprefix('hk').zfill(5) for x in oc.get('requested_codes',[])]
    if oc.get('expected_complete_session')!=target or requested!=codes or actual!=codes or len(set(actual))!=len(codes):raise ValueError('O_R0_COVERAGE_SET_MISMATCH')
    if oc.get('model_analysis_enabled') is not False or oc.get('model_credentials_provided') is not False:raise ValueError('O_R0_MODEL_BOUNDARY')
    valid=[r for r in oc['coverage'] if r.get('status')=='current_valid_bar' and r.get('latest_date')==target]
    if len(valid)!=oc.get('current_valid_count'):raise ValueError('O_R0_DECLARED_COVERAGE_MISMATCH')
    snap=out/'snapshot';snap.mkdir()
    ss=build_from_r0_seal(target,ROOT/'docs/dsa-u-universe.json',ROOT/'docs/runtime/run032_public_cache/O_UNIVERSE.json',sp,snap)
    if ss['formal_universe_available'] or (snap/'O_UNIVERSE.json').exists() or (snap/'U_UNIVERSE.json').exists():raise ValueError('R0_FORMAL_PROMOTION_FORBIDDEN')
    preliminary={'schema_version':1,'target_session':target,'source_seal_verified':True,'original_coverage_sha256':covhash,'source_artifact_sha256':seal['source_artifact_digest'],'O':{'source_run':O_RUN,'source_head':orun['head_sha'],'artifact_id':O_ART,'artifact_digest':O_DIGEST,'coverage_sha256':ochash,'scanned':len(actual),'current_valid':len(valid),'data_gaps':[{'code':r['code'],'status':r.get('status'),'latest_date':r.get('latest_date')} for r in oc['coverage'] if r not in valid],'state':'R0_SCAN_COMPLETE_WITH_EXPLICIT_GAPS','paid_model_calls':0},'snapshot':ss,'runtime_pointer_switch':False,'formal_generation':False,'paid_model_calls':0,'real_orders':0}
    (out/'SOURCE_AUDIT.json').write_text(json.dumps(preliminary,indent=2)+'\n');print('SEALED_SOURCE_AND_O_R0_VERIFIED '+json.dumps(preliminary),flush=True)
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('API_KEY','SECRET','TOKEN','WEBHOOK'))}
    ur=out/'u';rc=subprocess.run([sys.executable,str(ROOT/'scripts/dsa_daily_u_production_v1.py'),'--research-root',str(ROOT),'--target-session',target,'--snapshot-dir',str(snap),'--macro',str(ROOT/'docs/runtime/U_DAILY_MACRO_AUTHORITY_LATEST.json'),'--out',str(ur),'--dry-run'],cwd=ROOT,env=env,timeout=1200).returncode
    us=json.loads((ur/'STATUS.json').read_text()) if (ur/'STATUS.json').exists() else {'state':'U_STATUS_MISSING'}
    passed=rc==0 and us.get('r0_refresh_complete') is True and us.get('current_valid_count')==45 and us.get('paid_model_calls')==0 and us.get('state') in ('WAIT_U_MACRO_AUTHORITY','DRY_RUN_PREFLIGHT')
    result={**preliminary,'U':us,'status':'PASS_R0_ONLY' if passed else 'FAIL_U_R0_COVERAGE','observed_at':datetime.now(timezone.utc).isoformat(),'github_run_id':os.environ.get('GITHUB_RUN_ID'),'code_head':os.environ.get('GITHUB_SHA')}
    (out/'SNAPSHOT_R0_REPAIR_RECEIPT.json').write_text(json.dumps(result,indent=2)+'\n');print('SNAPSHOT_R0_REPAIR_RESULT '+json.dumps(result),flush=True)
    if not passed:raise SystemExit(2)
if __name__=='__main__':main()
