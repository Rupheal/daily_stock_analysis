"""Run058H: one authorized O-native provider slot after Run058G dry acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from dsa_drive_store import DriveStore,scoped_token
from o_provider_completion import inspect_completion
from o_release_quote_semantics import build_release_view
from o_release_gate_contract import evaluate_release_gate
from o_native_model_configuration import configure
from prepare_hk_pool_rollout_preflight_v2 import prepare as prepare_v2
from run_hk_bounded_native_members import write,balance,command,private_save

ACCEPTED={"PASS_NATIVE_AUTOMATED_PENDING_MANUAL_REVIEW","PASS_WITH_VERSIONED_RELEASE_ADAPTER_PENDING_MANUAL_REVIEW"}

def _dry_ready(summary,budget):
    hist=((summary.get("input_validation_receipt") or {}).get("full_native_history_window") or {})
    reqs=(budget or {}).get("requests") or []
    return (summary.get("input_validated") is True and hist.get("passed") is True and hist.get("every_native_bar_validated") is True
            and len(reqs)==1 and reqs[0].get("status")=="dry_envelope_validated_not_sent")

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--checkout",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--scope",type=Path,required=True);ap.add_argument("--plan",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();s=json.loads(a.scope.read_text())
    assert s["code"]=="00001" and s["maximum_requests"]==1 and s["maximum_cost_cny"]=="0.10" and s["per_member_cap_cny"]=="0.10"
    assert s["provider_send_authorized"] is True and s["automatic_retry"] is False
    assert os.environ.get("GITHUB_RUN_ATTEMPT")=="1" and os.environ.get("GITHUB_EVENT_NAME")=="push"
    assert hashlib.sha256(a.cache.read_bytes()).hexdigest()==s["history_cache_sha256"]
    dry_receipt=json.loads(Path(s["run058g_result"]).read_text())
    assert dry_receipt["exact_history_contract_pass"] is True and dry_receipt["model_http_requests"]==0 and dry_receipt["drive_claims"]==0

    a.out.mkdir(parents=True,exist_ok=False);code=s["code"];root=a.out/code;root.mkdir()
    row={"code":code,"status":"PENDING","model_http_requests_confirmed":0,"model_http_requests_possible":0,
         "qualified_signal":False,"private_persistence":None,"claim_persisted":False}
    artifact=s["artifact_prefix"]+"-"+code;run_id=s["run_id"]+"-"+code
    safe_env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    try:
        d=json.loads(Path(s["run058d_result"]).read_text())
        assert d["ready_for_new_paid_child"]==["00001"] and d["session_preflight_isolated"]==["00002"]
        repo=Path(__file__).resolve().parents[1];scripts=repo/"scripts";universe=repo/"docs/runtime/run032_public_cache/O_UNIVERSE.json"
        pre=root/"preflight";prepare_v2(code,s["target_session"],universe,a.cache,a.plan,pre)
        pf=pre/"preflight.json";preflight=json.loads(pf.read_text())
        assert preflight["passed"] is True and preflight["symbol"]=="HK00001" and preflight["target"]==s["target_session"]
        assert preflight["native_history_window"]["count"]>=21
        row["preflight_sha256"]=hashlib.sha256(pf.read_bytes()).hexdigest();row["fresh_preflight_status"]="PASS_POOL_TARGET_PREFLIGHT_V2"

        common=["--symbol","HK"+code,"--checkout",str(a.checkout.resolve()),"--expected-commit",s["frozen_upstream"],
                "--preflight",str(pf.resolve()),"--limit-cny","0.10","--carry-upper-cny","0","--target-boundary-adapter","--news-handoff-v1"]
        env=dict(safe_env,DSA_DEEPSEEK_V41_TOKENIZER=os.environ["DSA_DEEPSEEK_V41_TOKENIZER"],LLM_CHANNELS="deepseek",
                 LLM_DEEPSEEK_PROTOCOL="openai",LLM_DEEPSEEK_BASE_URL="https://api.deepseek.com",LLM_DEEPSEEK_MODELS="deepseek-flash",
                 LITELLM_MODEL="openai/deepseek-flash",LITELLM_FALLBACK_MODELS="",REPORT_INTEGRITY_RETRY="0",MAX_WORKERS="1",
                 DSA_INPUT_TOKEN_MARGIN="2048")
        env.update(configure(root,s["native_model_configuration"]));row["native_model_configuration"]=s["native_model_configuration"]

        dry=root/"dry";env.update(DSA_BUDGET_PROBE_ONLY="1",LLM_DEEPSEEK_API_KEY="dry-envelope-no-network",
                                  DSA_FROZEN_HISTORY_AUDIT_PATH=str((root/"dry-frozen-history-audit.json").resolve()))
        command(scripts/"run_hk_original_model_probe_run058g.py",[*common,"--output",str(dry)],env,root/"dry.stdout")
        budget=json.loads((dry/"budget.json").read_text());summary=json.loads((dry/"probe-summary.json").read_text())
        if not _dry_ready(summary,budget):raise ValueError("FREE_NATIVE_ENVELOPE_OR_HISTORY_FAILED")
        req=budget["requests"];upper=Decimal(req[0]["pre_send_peak_upper_cny"])
        if upper>Decimal("0.10"):raise ValueError("PRESEND_COST_CAP_EXCEEDED")
        row["pre_send_upper_cny"]=str(upper);row["dry_payload_sha256"]=req[0]["payload_sha256"]
        row["pre_send_private_persistence"]=private_save(root,artifact+"-PRE-SEND",run_id)
        if not row["pre_send_private_persistence"].get("save_read_hash_restore"):raise ValueError("PRE_SEND_PRIVATE_SAVE_UNVERIFIED")

        before=balance();write(root/"private-balance-before.json",{"currency":"CNY","available_balance":str(before),"retrieved_at":datetime.now(timezone.utc).isoformat()})
        if before<Decimal("0.10"):raise ValueError("BUDGET_OR_BALANCE_INSUFFICIENT")
        with httpx.Client(timeout=30,follow_redirects=False) as c:
            c.headers["Authorization"]="Bearer "+scoped_token(c);store=DriveStore(c,os.environ["DSA_DRIVE_FOLDER_ID"])
            claim=store.reserve_native_call(artifact,run_id,row["preflight_sha256"],"CI-"+os.environ["GITHUB_RUN_ID"]+"-"+code)
        write(root/"private-claim.json",claim);row["claim_persisted"]=True

        actual=root/"native";env.update(DSA_BUDGET_PROBE_ONLY="0",LLM_DEEPSEEK_API_KEY=os.environ["DEEPSEEK_API_KEY"],
                                       DSA_FROZEN_HISTORY_AUDIT_PATH=str((root/"native-frozen-history-audit.json").resolve()))
        rc=command(scripts/"run_hk_original_model_probe_run058g.py",[*common,"--output",str(actual)],env,root/"native.stdout");row["native_exit_code"]=rc
        b=json.loads((actual/"budget.json").read_text());requests=b.get("requests") or []
        row["model_http_requests_possible"]=len(requests);row["model_http_requests_confirmed"]=sum(x.get("status")=="response_received" for x in requests)
        if len(requests)>1 or row["model_http_requests_confirmed"]>1:raise ValueError("MULTIPLE_PROVIDER_REQUESTS_FORBIDDEN")
        row["usage_peak_estimate_cny"]=str(sum(Decimal(x.get("usage_peak_estimate_cny",x.get("charge_upper_cny","0"))) for x in requests))
        row["usage"]=[x.get("usage") for x in requests]
        if row["model_http_requests_confirmed"]!=1:raise ValueError("PROVIDER_RESPONSE_NOT_CONFIRMED")
        try:
            after=balance();write(root/"private-balance-after.json",{"currency":"CNY","available_balance":str(after),"retrieved_at":datetime.now(timezone.utc).isoformat()})
            row["observed_balance_change_cny"]=str(before-after)
        except Exception:row["observed_balance_change_cny"]=None
        row["actual_attributable_charge_cny"]=None
        completion=inspect_completion((actual/"provider-response.txt").read_bytes());write(actual/"provider-completion-audit.json",completion);row["provider_completion"]=completion
        if completion["status"]!="PASS":raise ValueError("|".join(completion["blockers"]))
        post=json.loads((actual/"post-output-contract.json").read_text());gate=post.get("promotion_gate") or {}
        row["raw_blockers"]=gate.get("blockers",[]);row["raw_gate"]=gate.get("status")
        if gate.get("status")=="PASS":row["status"]="PASS_NATIVE_AUTOMATED_PENDING_MANUAL_REVIEW"
        elif set(row["raw_blockers"])=={"SEM-001"}:
            inp=json.loads((actual/"original-input.json").read_text());raw=json.loads((actual/"pipeline-final-result.json").read_text())
            release=build_release_view(preflight,inp,raw);rg=evaluate_release_gate(post,release)
            write(root/"release-view.json",release);write(root/"release-gate.json",rg);row["release_strategy_fields_changed"]=release["receipt"]["strategy_fields_changed"]
            row["status"]=rg["status"]+"_PENDING_MANUAL_REVIEW"
        else:row["status"]="NATIVE_OUTPUT_ISOLATED"
    except Exception as exc:
        if row["status"]=="PENDING":row["status"]="ISOLATED"
        row["failure_class"]=type(exc).__name__;row["failure_code"]=str(exc)[:180] if isinstance(exc,(ValueError,AssertionError)) else type(exc).__name__
        if row.get("claim_persisted") and row["model_http_requests_possible"]==0:
            p=root/"native"/"budget.json"
            if p.exists():
                q=json.loads(p.read_text()).get("requests") or [];row["model_http_requests_possible"]=len(q);row["model_http_requests_confirmed"]=sum(x.get("status")=="response_received" for x in q)
            else:row["model_http_requests_possible"]=1
    finally:
        write(root/"member-summary.json",row)
        try:row["private_persistence"]=private_save(root,artifact,run_id)
        except Exception as exc:row["private_persistence"]={"status":"FAIL","reason":type(exc).__name__}
        write(root/"member-summary.json",row)
        accepted=(row["status"] in ACCEPTED and row["model_http_requests_confirmed"]==1 and (row["private_persistence"] or {}).get("save_read_hash_restore") is True)
        result={"schema_version":1,"run_id":s["run_id"],"O_denominator":660,"attempted_members":1,"members":[row],
                "model_http_requests_confirmed":row["model_http_requests_confirmed"],"model_http_requests_possible":row["model_http_requests_possible"],
                "maximum_cost_cny":"0.10","actual_attributable_charge_cny":row.get("actual_attributable_charge_cny"),
                "qualified_signals":0,"formal_pool_top3_generated":False,"simulation_ledger_writes":0,"manual_review_required":True,"accepted_member":accepted}
        write(a.out/"SANITIZED_RESULT.json",result);print("RUN058H_SANITIZED "+json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
