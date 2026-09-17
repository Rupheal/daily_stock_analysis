"""Run058 controller v2: append-only reconciliation without rewriting failed history."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

RUN_ID="TRI-DSA-RESUME-20260917-058"
READY_STATE="READY_CHILD_ENVELOPE"
HOLD_STATE="HOLD_NO_CHILD"
TERMINAL_BATCH_STATES={"ACCEPTED_NATIVE","RAW_GATE_BLOCK"}
HOLD_BATCH_STATES={"CLAIMED_RECONCILE","PRIVATE_PRESEND_FAIL","BALANCE_FAIL","PROVIDER_FAIL_AFTER_CLAIM","PRIVATE_FINAL_FAIL","STOP_TRANCHE"}
ALLOWED_LEDGER_STATES=TERMINAL_BATCH_STATES|HOLD_BATCH_STATES

def sha256_bytes(raw): return hashlib.sha256(raw).hexdigest()
def read_json(p):
    raw=p.read_bytes(); return json.loads(raw),sha256_bytes(raw)
def read_jsonl(p):
    if not p.exists(): return [],None
    raw=p.read_bytes(); rows=[]
    for n,line in enumerate(raw.decode().splitlines(),1):
        if not line.strip(): continue
        try: rows.append(json.loads(line))
        except json.JSONDecodeError as exc: raise ValueError(f"BAD_LEDGER_JSON_LINE:{n}") from exc
    return rows,sha256_bytes(raw)

def validate_plan(plan,scope):
    counts=scope["frozen_counts"]; d=plan.get("denominator") or {}; ro=plan.get("rollout") or {}; nr=plan.get("no_repeat") or {}
    if plan.get("state")!="PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN": raise ValueError("RUN057_PLAN_NOT_ACCEPTED")
    checks=[
      (d.get("O_universe"),counts["O_universe"],"O_DENOMINATOR_CHANGED"),
      (d.get("deterministic_ready"),counts["deterministic_ready"],"O_READY_COUNT_CHANGED"),
      (d.get("retained_isolated"),counts["retained_isolated"],"O_ISOLATED_COUNT_CHANGED"),
      (nr.get("count_within_ready"),counts["no_repeat_ready"],"NO_REPEAT_COUNT_CHANGED"),
      (ro.get("never_called_count"),counts["never_called"],"NEVER_CALLED_COUNT_CHANGED"),
      (ro.get("micro_batch_count"),counts["micro_batch_count"],"MICROBATCH_COUNT_CHANGED"),
      (ro.get("tranche_count"),counts["planning_tranche_count"],"TRANCHE_COUNT_CHANGED")]
    for a,b,e in checks:
        if a!=b: raise ValueError(e)
    if ro.get("micro_batch_width")!=2: raise ValueError("UNPROVEN_MICROBATCH_WIDTH")
    if ro.get("send_authorized_by_run057") is not False: raise ValueError("RUN057_MUST_NOT_AUTHORIZE_SEND")

def effective_status(row):
    status=row["status"]; resolution=row.get("resolution_status")
    if resolution is None:return status
    if status!="STOP_TRANCHE": raise ValueError("RESOLUTION_ONLY_ALLOWED_FOR_STOP_TRANCHE")
    if resolution not in TERMINAL_BATCH_STATES: raise ValueError("BAD_RESOLUTION_STATUS")
    if row.get("resolution_verified") is not True: raise ValueError("UNVERIFIED_RESOLUTION")
    if not row.get("resolution_run_id"): raise ValueError("MISSING_RESOLUTION_RUN_ID")
    return resolution

def validate_ledger(rows,plan):
    batches={x["micro_batch_id"]:x for x in plan["rollout"]["micro_batches"]}; latest={}
    for i,row in enumerate(rows):
        bid=row.get("micro_batch_id"); status=row.get("status")
        if bid not in batches: raise ValueError(f"LEDGER_UNKNOWN_BATCH:{bid}")
        if status not in ALLOWED_LEDGER_STATES: raise ValueError(f"LEDGER_BAD_STATUS:{status}")
        if row.get("codes")!=batches[bid]["codes"]: raise ValueError(f"LEDGER_CODE_MISMATCH:{bid}")
        prior=latest.get(bid)
        if prior is not None and prior.get("status")!=status:
            raise ValueError(f"LEDGER_CONFLICTING_STATE:{bid}")
        # A reconciliation is append-only refinement of the same failed state.
        if row.get("resolution_status") is not None:
            effective_status(row)
            if prior is None or prior.get("status")!="STOP_TRANCHE":
                raise ValueError(f"RESOLUTION_WITHOUT_PRIOR_STOP:{bid}")
        latest[bid]={**row,"_line_index":i}
    return latest

def tranche_for_batch(plan,bid):
    m=[t for t in plan["rollout"]["tranches"] if bid in t["micro_batch_ids"]]
    if len(m)!=1: raise ValueError(f"TRANCHE_BINDING_FAIL:{bid}")
    return m[0]

def build(plan,scope,rows,plan_sha,ledger_sha):
    validate_plan(plan,scope); latest=validate_ledger(rows,plan)
    never=set(plan["rollout"]["never_called_codes"]); forbidden=set(plan["isolation"]["codes"])|set(plan["no_repeat"]["spent_codes_within_ready"])
    holds=[]
    for bid,row in latest.items():
        eff=effective_status(row)
        if eff in HOLD_BATCH_STATES: holds.append({"micro_batch_id":bid,"status":row["status"],"effective_status":eff,"codes":row["codes"]})
    if holds:
        return {"schema_version":2,"run_id":RUN_ID,"state":HOLD_STATE,"target_session":scope["target_session"],
          "reason":"UNRESOLVED_FAIL_CLOSED_LEDGER_STATE","holds":sorted(holds,key=lambda x:x["micro_batch_id"]),"selected_child":None,
          "plan_sha256":plan_sha,"ledger_sha256":ledger_sha,"resource_accounting":scope["resource_plan"],
          "next":"Append a verified reconciliation for the same STOP_TRANCHE state; never rewrite or delete the original row."}
    selected=None
    for b in plan["rollout"]["micro_batches"]:
        row=latest.get(b["micro_batch_id"])
        if row and effective_status(row) in TERMINAL_BATCH_STATES: continue
        codes=b["codes"]
        if not set(codes)<=never: raise ValueError(f"BATCH_NOT_NEVER_CALLED:{b['micro_batch_id']}")
        if set(codes)&forbidden: raise ValueError(f"BATCH_CONTAINS_FORBIDDEN_CODE:{b['micro_batch_id']}")
        selected=b;break
    if selected is None:
        return {"schema_version":2,"run_id":RUN_ID,"state":HOLD_STATE,"target_session":scope["target_session"],
          "reason":"ALL_RUN057_NEVER_CALLED_BATCHES_TERMINAL","holds":[],"selected_child":None,"plan_sha256":plan_sha,
          "ledger_sha256":ledger_sha,"resource_accounting":scope["resource_plan"],"next":"Proceed only to later full-pool reconciliation under a separate gate."}
    tranche=tranche_for_batch(plan,selected["micro_batch_id"]); child=scope["child_contract"]; cap=f"{0.10*len(selected['codes']):.2f}"
    if cap!=selected["hard_cap_cny"] or cap!=child["child_hard_cap_cny"]: raise ValueError("CHILD_COST_CAP_MISMATCH")
    return {"schema_version":2,"run_id":RUN_ID,"state":READY_STATE,"target_session":scope["target_session"],
      "plan_sha256":plan_sha,"ledger_sha256":ledger_sha,
      "denominator":{"O_universe":660,"deterministic_ready":608,"retained_isolated":52,"no_repeat_ready":3,"never_called":605},
      "ledger_summary":{"rows":len(rows),"terminal_batches":sum(effective_status(x) in TERMINAL_BATCH_STATES for x in latest.values()),"hold_batches":0},
      "selected_child":{"proposed_child_run_id":child["proposed_child_run_id"],"micro_batch_id":selected["micro_batch_id"],
       "tranche_id":tranche["tranche_id"],"codes":selected["codes"],"member_count":len(selected["codes"]),
       "per_member_hard_cap_cny":child["per_member_hard_cap_cny"],"child_hard_cap_cny":cap,
       "native_model_configuration":child["native_model_configuration"],"required_pre_send_gates":child["required_pre_send_gates"],
       "required_post_send_gates":child["required_post_send_gates"],"drive_claim_reconciliation_required_before_send":True,
       "automatic_retry_after_claim":False,"provider_send_authorized_by_run058":False},
      "resource_accounting":scope["resource_plan"],
      "next":"Create a new immutable child scope. Re-run fresh gates and Drive claim reconciliation; this controller never authorizes provider send."}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--scope",type=Path,required=True);ap.add_argument("--plan",type=Path,required=True);ap.add_argument("--ledger",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args();scope,_=read_json(a.scope);plan,ps=read_json(a.plan);rows,ls=read_jsonl(a.ledger)
    if scope.get("run_id")!=RUN_ID or scope.get("resource_plan",{}).get("model_http_requests")!=0: raise ValueError("RUN058_SCOPE_MISMATCH")
    out=build(plan,scope,rows,ps,ls);a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"state":out["state"],"selected_child":out.get("selected_child"),"model_http_requests":0},ensure_ascii=False))
if __name__=="__main__":main()
