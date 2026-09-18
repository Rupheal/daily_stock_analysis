from __future__ import annotations
import argparse, json, os, subprocess, sys, sqlite3
from pathlib import Path
from prepare_hk_pool_rollout_preflight_v2 import prepare as prepare_v2
from o_native_model_configuration import configure

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkout",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[1]
    pre=a.out/"preflight"
    prepare_v2("00001","2026-09-17",repo/"docs/runtime/run032_public_cache/O_UNIVERSE.json",
               a.cache,repo/"docs/runtime/RUN057_O_NATIVE_PLAN.json",pre)
    pf=json.loads((pre/"preflight.json").read_text())
    expected=pf["validated_native_history"]

    env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    env.update({
      "DSA_DEEPSEEK_V41_TOKENIZER":os.environ["DSA_DEEPSEEK_V41_TOKENIZER"],
      "LLM_CHANNELS":"deepseek","LLM_DEEPSEEK_PROTOCOL":"openai","LLM_DEEPSEEK_BASE_URL":"https://api.deepseek.com",
      "LLM_DEEPSEEK_MODELS":"deepseek-flash","LITELLM_MODEL":"openai/deepseek-flash","LITELLM_FALLBACK_MODELS":"",
      "REPORT_INTEGRITY_RETRY":"0","MAX_WORKERS":"1","DSA_INPUT_TOKEN_MARGIN":"2048",
      "DSA_BUDGET_PROBE_ONLY":"1","LLM_DEEPSEEK_API_KEY":"dry-envelope-no-network",
    })
    env.update(configure(a.out,"O_DEEPSEEK_FLASH_NONTHINKING_v1"))
    dry=a.out/"dry"
    cmd=[sys.executable,str(repo/"scripts/run_hk_original_model_probe_run030.py"),
         "--symbol","HK00001","--checkout",str(a.checkout.resolve()),
         "--expected-commit","089d9d26d68f8b839ea5a74a3784e4402925f8b7",
         "--preflight",str((pre/"preflight.json").resolve()),"--output",str(dry),
         "--limit-cny","0.10","--carry-upper-cny","0","--target-boundary-adapter","--news-handoff-v1"]
    p=subprocess.run(cmd,env=env,text=True,capture_output=True,timeout=600)

    db=dry/"original-data.db"
    actual=[]
    if db.exists():
        with sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True) as con:
            actual=con.execute("SELECT date,open,high,low,close,volume FROM stock_daily WHERE code=? COLLATE NOCASE ORDER BY date",("HK00001",)).fetchall()
    by={str(r[0])[:10]:r for r in actual}
    diffs=[]
    for ref in expected:
        d=ref["date"]; r=by.get(d)
        if not r:
            diffs.append({"date":d,"missing_actual":True}); continue
        ev=float(ref["volume"]); av=float(r[5]); absd=abs(av-ev)
        rel=None if ev==0 else abs(av/ev-1.0)
        if av!=ev:
            diffs.append({"date":d,"expected_volume":ev,"actual_volume":av,"absolute_delta":absd,"relative_delta":rel,
                          "target_session":d=="2026-09-17"})
    out={
      "schema_version":1,"run_id":"TRI-DSA-O-VOLUME-DIFF-20260918-058G",
      "dry_returncode":p.returncode,"expected_count":len(expected),"actual_count":len(actual),
      "volume_diff_count":len(diffs),"volume_diffs":diffs,
      "target_session_diff":next((x for x in diffs if x.get("target_session")),None),
      "max_relative_delta":max((x["relative_delta"] for x in diffs if x.get("relative_delta") is not None),default=0),
      "model_http_requests":0,"provider_credentials_used":False,"DeepSeek_API_cost_cny":0,"drive_claims":0,"real_orders":0,
      "diagnostic_only":True,
    }
    (a.out/"RUN058G_RESULT.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(out,ensure_ascii=False))
if __name__=="__main__": main()
