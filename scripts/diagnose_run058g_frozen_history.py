from __future__ import annotations
import argparse,json,os,subprocess,sys
from pathlib import Path
from prepare_hk_pool_rollout_preflight_v2 import prepare as prepare_v2
from o_native_model_configuration import configure

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--checkout",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False);repo=Path(__file__).resolve().parents[1]
    pre=a.out/"preflight";prepare_v2("00001","2026-09-17",repo/"docs/runtime/run032_public_cache/O_UNIVERSE.json",a.cache,repo/"docs/runtime/RUN057_O_NATIVE_PLAN.json",pre)
    env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    env.update({"DSA_DEEPSEEK_V41_TOKENIZER":os.environ["DSA_DEEPSEEK_V41_TOKENIZER"],"LLM_CHANNELS":"deepseek","LLM_DEEPSEEK_PROTOCOL":"openai",
      "LLM_DEEPSEEK_BASE_URL":"https://api.deepseek.com","LLM_DEEPSEEK_MODELS":"deepseek-flash","LITELLM_MODEL":"openai/deepseek-flash","LITELLM_FALLBACK_MODELS":"",
      "REPORT_INTEGRITY_RETRY":"0","MAX_WORKERS":"1","DSA_INPUT_TOKEN_MARGIN":"2048","DSA_BUDGET_PROBE_ONLY":"1","LLM_DEEPSEEK_API_KEY":"dry-envelope-no-network",
      "DSA_FROZEN_HISTORY_AUDIT_PATH":str((a.out/"frozen-history-audit.json").resolve())})
    env.update(configure(a.out,"O_DEEPSEEK_FLASH_NONTHINKING_v1"))
    cmd=[sys.executable,str(repo/"scripts/run_hk_original_model_probe_run058g.py"),"--symbol","HK00001","--checkout",str(a.checkout.resolve()),
      "--expected-commit","089d9d26d68f8b839ea5a74a3784e4402925f8b7","--preflight",str((pre/"preflight.json").resolve()),
      "--output",str(a.out/"dry"),"--limit-cny","0.10","--carry-upper-cny","0","--target-boundary-adapter","--news-handoff-v1"]
    p=subprocess.run(cmd,env=env,text=True,capture_output=True,timeout=600)
    result={"schema_version":1,"run_id":"TRI-DSA-O-FROZEN-HISTORY-DRY-20260918-058G","returncode":p.returncode,
      "stdout_tail":p.stdout.splitlines()[-100:],"stderr_tail":p.stderr.splitlines()[-80:],
      "model_http_requests":0,"provider_credentials_used":False,"DeepSeek_API_cost_cny":0,"drive_claims":0,"real_orders":0}
    for name in ("budget.json","probe-summary.json"):
      q=a.out/"dry"/name
      if q.exists():result[name[:-5].replace("-","_")]=json.loads(q.read_text())
    q=a.out/"frozen-history-audit.json"
    if q.exists():result["frozen_history_audit"]=json.loads(q.read_text())
    summary=result.get("probe_summary",{})
    hist=((summary.get("input_validation_receipt") or {}).get("full_native_history_window") or {})
    reqs=(result.get("budget") or {}).get("requests") or []
    result["exact_history_contract_pass"]=(
        summary.get("input_validated") is True
        and hist.get("passed") is True
        and hist.get("every_native_bar_validated") is True
        and len(reqs)==1
        and reqs[0].get("status")=="dry_envelope_validated_not_sent"
    )
    (a.out/"RUN058G_RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
