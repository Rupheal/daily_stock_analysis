#!/usr/bin/env python3
"""Deterministic, sanitized DSA Dashboard feed generator. No network/model access."""
from __future__ import annotations
import argparse, json, os, re
from datetime import datetime, timezone
from pathlib import Path

BRANCH="fix/native-private-execution-20260914"
SECRET_RE=re.compile(r"(?i)(api[_-]?key|secret|token|refresh[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,}\]]+")

def load(p:Path, default=None):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return default

def make_feed(root:Path, source_commit:str)->dict:
    nxt=load(root/"docs/DSA_NEXT_ACTIONS.json",{}) or {}
    cap=load(root/"docs/runtime/O_FINAL_CAPTURE_005_RESULT.json",{}) or {}
    now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    boundaries=cap.get("formal_boundaries",{})
    latest_run=cap.get("run_id") or nxt.get("native_execution_20260914",{}).get("run_id")
    o_accepted=1 if boundaries.get("o_single_stock_formally_accepted") else 0
    u_accepted=int(boundaries.get("u45_formal_acceptance_added") or nxt.get("native_execution_20260914",{}).get("U_execution_accepted") or 0)
    sim="ELIGIBLE" if boundaries.get("simulated_fills",0) else "WAIT_NOT_ELIGIBLE"
    feed={
      "meta":{"schema_version":"0.18","generated_at":now,"source_commit":source_commit,"branch":BRANCH,"latest_validated_run":latest_run,"evidence_timestamp":now},
      "system":{"overall_state":"BLOCKED" if not o_accepted else "LIVE","current_stage":"O_GATE_A_PREAUTH_PREPARATION" if not o_accepted else "O_GATE_A_ACCEPTED","next_action":(cap.get("next_actions") or ["Continue deterministic preparation"])[-1],"last_successful_gate":"FINAL_PIPELINE_CAPTURE_ACCEPTED" if cap.get("resolution",{}).get("updated_observer_has_final_pipeline_capture") else "NOT_VERIFIED","blocking_gate":None if o_accepted else "NEW_O_GATE_A_PROVIDER_SLOT_NOT_AUTHORIZED","error_code":None if o_accepted else "OWNER_AUTH_REQUIRED_FOR_NEW_PROVIDER_SLOT"},
      "O":{"denominator":None,"attempted":None,"succeeded":None,"failed":None,"accepted":o_accepted,"top3":[],"signal":"WAIT","qualified_buy":False,"latest_session":None,"model_http_requests":int(cap.get("resources",{}).get("new_model_requests") or 0),"input_tokens":0,"output_tokens":0,"total_tokens":0,"estimated_or_actual_cost":cap.get("resources",{}).get("model_request_cost_cny",0),"evidence_status":"LAST_VALIDATED_NO_GO_CHILD2; NEW_GATE_A_NOT_RUN" if not o_accepted else "ACCEPTED"},
      "U":{"denominator":45,"attempted":0,"succeeded":0,"failed":0,"accepted":u_accepted,"top3":[],"signal":"WAIT","qualified_buy":False},
      "data_health":{"fresh_preflight":"NOT_VERIFIED_FOR_NEW_GATE_A","provider":"PREP_REQUIRED","session":"PREP_REQUIRED","OHLC":"PREP_REQUIRED","volume":"CALIBRATION_AVAILABLE_RECHECK_REQUIRED","news":"PREP_REQUIRED","issuer":"PREP_REQUIRED","manifest":"PREP_REQUIRED"},
      "observer":{"pass_fail":"PASS_FINAL_CAPTURE_ENGINEERING" if cap.get("resolution",{}).get("updated_observer_has_final_pipeline_capture") else "NOT_VERIFIED","block_count":0,"latest_error_code":None},
      "storage":{"save":"PASS_HISTORICAL","independent_read":"PASS_HISTORICAL","sha_match":"PASS_HISTORICAL","revision_check":"PASS_HISTORICAL","restore_verified":"PASS_HISTORICAL","canonical_claim_count":1,"canonical_native_count":1},
      "budget":{"affordability":"NOT_VERIFIED_FOR_NEW_GATE_A","request_limit":0,"actual_request_count":0,"tokens":{"input":0,"output":0,"total":0},"cost":cap.get("resources",{}).get("model_request_cost_cny",0)},
      "simulation":{"eligibility":sim,"account_A":"NOT_VERIFIED","account_B":"NOT_VERIFIED","cash":"NOT_VERIFIED","positions":"NOT_VERIFIED","pnl":"NOT_VERIFIED","pending_signal":"WAIT"},
      "shadow_week":{"date":now[:10],"data_pass_rate":"NOT_VERIFIED","observer_block_rate":"NOT_VERIFIED","model_success_rate":"NOT_APPLICABLE_NO_MODEL_CALL","cost_per_accepted_analysis":"NOT_APPLICABLE","O_coverage":f"{o_accepted} accepted / denominator not yet frozen","U_coverage":f"{u_accepted}/45 formal accepted","top3_turnover":"NOT_VERIFIED","signal_persistence":"WAIT","BUY_WAIT":"WAIT","simulation_eligibility":sim},
      "debug":{"provider_error":None,"preflight_error":None,"observer_error":None,"drive_error":None,"model_error":"CHILD2_SEMANTIC_NO_GO_PRESERVED" if not o_accepted else None,"recovery_state":"NEW_CASE_REQUIRED" if not o_accepted else "NONE","recovery_condition":"Do not retry CHILD2; complete fresh Gate A preauth and obtain explicit owner authorization for a new provider slot." if not o_accepted else "NONE"}
    }
    text=json.dumps(feed,ensure_ascii=False)
    if SECRET_RE.search(text): raise SystemExit("sanitized feed failed secret scan")
    if feed["U"]["denominator"]!=45: raise SystemExit("U denominator invariant failed")
    return feed

def append_history(history_path:Path, feed:dict):
    history=load(history_path,{"schema_version":"0.18","append_only":True,"days":[]}) or {"schema_version":"0.18","append_only":True,"days":[]}
    days=history.setdefault("days",[]); d=feed["shadow_week"].copy(); d["latest_validated_run"]=feed["meta"]["latest_validated_run"]; d["model_requests"]=feed["budget"]["actual_request_count"]; d["input_tokens"]=feed["budget"]["tokens"]["input"]; d["output_tokens"]=feed["budget"]["tokens"]["output"]; d["total_tokens"]=feed["budget"]["tokens"]["total"]; d["cost"]=feed["budget"]["cost"]; d["provider_failures"]=feed["debug"]["provider_error"]; d["Drive_status"]=feed["storage"]["restore_verified"]; d["blocking_gate"]=feed["system"]["blocking_gate"]
    existing={x.get("date") for x in days}
    if d["date"] not in existing: days.append(d)
    history_path.write_text(json.dumps(history,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=".");ap.add_argument("--out",default="DSA_DASHBOARD_LIVE.json");ap.add_argument("--history",default="DSA_DASHBOARD_HISTORY.json");ap.add_argument("--source-commit",default=os.environ.get("GITHUB_SHA","UNKNOWN"));args=ap.parse_args()
    root=Path(args.root);feed=make_feed(root,args.source_commit);Path(args.out).write_text(json.dumps(feed,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");append_history(Path(args.history),feed)
if __name__=="__main__": main()
