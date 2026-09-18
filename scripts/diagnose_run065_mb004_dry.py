from __future__ import annotations
import argparse,json,os,subprocess,sys,hashlib
from pathlib import Path
from o_native_model_configuration import configure

def run_one(code, checkout, cache, universe, repo, out):
    root=out/code;root.mkdir(parents=True)
    pre=root/'preflight'
    p=subprocess.run([
      sys.executable,str(repo/'scripts/prepare_run061_current_preflight.py'),
      '--code',code,'--target','2026-09-18','--universe',str(universe),
      '--cache',str(cache),'--plan',str(repo/'docs/runtime/RUN057_O_NATIVE_PLAN.json'),'--out',str(pre)
    ],text=True,capture_output=True,timeout=120)
    rec={'code':code,'preflight_returncode':p.returncode,'preflight_stdout_tail':p.stdout.splitlines()[-20:],
         'preflight_stderr_tail':p.stderr.splitlines()[-20:],
         'model_http_requests':0,'provider_credentials_used':False,'drive_claims':0}
    if p.returncode!=0 or not (pre/'preflight.json').exists():
        rec['state']='FREE_PREFLIGHT_FAILED';return rec
    pf=pre/'preflight.json';rec['preflight_sha256']=hashlib.sha256(pf.read_bytes()).hexdigest()
    env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ('SECRET','TOKEN','API_KEY','WEBHOOK','DSA_DRIVE'))}
    env.update({
      'DSA_DEEPSEEK_V41_TOKENIZER':os.environ['DSA_DEEPSEEK_V41_TOKENIZER'],
      'LLM_CHANNELS':'deepseek','LLM_DEEPSEEK_PROTOCOL':'openai','LLM_DEEPSEEK_BASE_URL':'https://api.deepseek.com',
      'LLM_DEEPSEEK_MODELS':'deepseek-flash','LITELLM_MODEL':'openai/deepseek-flash','LITELLM_FALLBACK_MODELS':'',
      'REPORT_INTEGRITY_RETRY':'0','MAX_WORKERS':'1','DSA_INPUT_TOKEN_MARGIN':'2048',
      'DSA_BUDGET_PROBE_ONLY':'1','LLM_DEEPSEEK_API_KEY':'dry-envelope-no-network',
    })
    env.update(configure(root,'O_DEEPSEEK_FLASH_NONTHINKING_v1'))
    dry=root/'dry'
    q=subprocess.run([
      sys.executable,str(repo/'scripts/run_hk_original_model_probe_run030.py'),
      '--symbol','HK'+code,'--checkout',str(checkout),'--expected-commit','089d9d26d68f8b839ea5a74a3784e4402925f8b7',
      '--preflight',str(pf.resolve()),'--output',str(dry),'--limit-cny','0.10','--carry-upper-cny','0',
      '--target-boundary-adapter','--news-handoff-v1','--frozen-native-history-adapter'
    ],env=env,text=True,capture_output=True,timeout=600)
    rec.update({'state':'DRY_COMPLETED','dry_returncode':q.returncode,
                'dry_stdout_tail':q.stdout.splitlines()[-100:],'dry_stderr_tail':q.stderr.splitlines()[-50:]})
    bp=dry/'budget.json'
    if bp.exists():rec['budget']=json.loads(bp.read_text())
    sp=dry/'probe-summary.json'
    if sp.exists():rec['probe_summary']=json.loads(sp.read_text())
    return rec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkout',type=Path,required=True);ap.add_argument('--cache',type=Path,required=True)
    ap.add_argument('--universe',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False);repo=Path(__file__).resolve().parents[1]
    rows=[run_one(c,a.checkout.resolve(),a.cache.resolve(),a.universe.resolve(),repo,a.out) for c in ('00008','00010')]
    result={'schema_version':1,'run_id':'TRI-DSA-O-DRY-DIAG-20260918-065','target_session':'2026-09-18',
            'micro_batch_id':'O57-MB-004','members':rows,'model_http_requests':0,'DeepSeek_API_cost_cny':0,
            'provider_credentials_used':False,'drive_claims':0,'real_orders':0,'automatic_retry':False}
    (a.out/'RUN065_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
