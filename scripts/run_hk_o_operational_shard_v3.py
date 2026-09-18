#!/usr/bin/env python3
"""O operational shard runner v3.

One provider request maximum per member. Member failures are terminal for that
session and do not stop the rest of the shard unless a repeated shared/provider
infrastructure failure indicates continuing would waste claims/cost.

Raw inputs/outputs stay in private Drive multipart evidence. Public shard output
contains only status, hashes, usage, semantic guard IDs, and strategy-core fields.
"""
from __future__ import annotations

import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import httpx

from dsa_drive_store import DriveStore,scoped_token,StoreError
from o_strategy_core_acceptance import evaluate as evaluate_core

PER_MEMBER_CAP=Decimal("0.10")


def write(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def command(script,args,env,log):
    with log.open("w") as handle:
        return subprocess.run([sys.executable,str(script),*args],env=env,stdout=handle,stderr=subprocess.STDOUT,timeout=600).returncode


def balance():
    with httpx.Client(timeout=20) as c:
        r=c.get("https://api.deepseek.com/user/balance",headers={"Authorization":"Bearer "+os.environ["DEEPSEEK_API_KEY"]})
        r.raise_for_status();d=r.json()
    rows=[x for x in d.get("balance_infos",[]) if x.get("currency")=="CNY"]
    if not d.get("is_available") or len(rows)!=1:
        raise ValueError("AVAILABLE_CNY_BALANCE_UNVERIFIED")
    return Decimal(rows[0]["total_balance"])


def private_save(root,artifact_id,run_id):
    from dsa_private_multipart import save
    with httpx.Client(timeout=30,follow_redirects=False) as c:
        c.headers["Authorization"]="Bearer "+scoped_token(c)
        s=DriveStore(c,os.environ["DSA_DRIVE_FOLDER_ID"])
        return save(root,artifact_id,run_id,s)


def reserve(artifact,run_id,preflight_sha,code):
    with httpx.Client(timeout=30,follow_redirects=False) as c:
        c.headers["Authorization"]="Bearer "+scoped_token(c)
        store=DriveStore(c,os.environ["DSA_DRIVE_FOLDER_ID"])
        return store.reserve_native_call(artifact,run_id,preflight_sha,"CI-"+os.environ["GITHUB_RUN_ID"]+"-"+code)


def select_operational_members(universe:dict,policy:dict):
    cur=policy.get("current_session") or {}
    official=universe.get("members") or []
    if len(official)!=cur.get("official_denominator") or len(official)!=660:
        raise ValueError("OFFICIAL_UNIVERSE_COUNT_MISMATCH")
    excluded={x.get("code") for x in cur.get("excluded_unresolved") or []}
    rows=[]
    seen=set()
    for idx,m in enumerate(official):
        code=str(m.get("code") or "")
        if not code or code in seen:
            raise ValueError("OFFICIAL_UNIVERSE_DUPLICATE_OR_EMPTY_CODE")
        seen.add(code)
        if code in excluded:
            continue
        rows.append({"code":code,"universe_index":idx,"official_name":m.get("official_name")})
    if len(rows)!=cur.get("operational_denominator"):
        raise ValueError("OPERATIONAL_DENOMINATOR_MISMATCH")
    return rows


def partition_members(rows:list[dict],shard_index:int,shard_count:int):
    if shard_count<1 or shard_index<0 or shard_index>=shard_count:
        raise ValueError("BAD_SHARD")
    n=len(rows)
    q,r=divmod(n,shard_count)
    start=shard_index*q+min(shard_index,r)
    size=q+(1 if shard_index<r else 0)
    return rows[start:start+size]


def _sanitize_failure(exc:Exception):
    text=str(exc)
    if isinstance(exc,(ValueError,AssertionError,StoreError)) and text and len(text)<=180:
        if all(ch.isalnum() or ch in "_:-. |/" for ch in text):
            return text
    return type(exc).__name__


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkout",type=Path,required=True)
    ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--universe",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True)
    ap.add_argument("--scope",type=Path,required=True)
    ap.add_argument("--codes-file",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    s=json.loads(a.scope.read_text());policy=json.loads(a.policy.read_text());universe=json.loads(a.universe.read_text())
    code_rows=json.loads(a.codes_file.read_text())
    a.out.mkdir(parents=True,exist_ok=False)

    if s["target_session"]!=(policy.get("current_session") or {}).get("session"):
        raise ValueError("TARGET_POLICY_SESSION_MISMATCH")
    if s["frozen_upstream"]!="089d9d26d68f8b839ea5a74a3784e4402925f8b7":
        raise ValueError("FROZEN_UPSTREAM_CHANGED")
    if Decimal(s["per_member_hard_cap_cny"])!=PER_MEMBER_CAP:
        raise ValueError("PER_MEMBER_CAP_CHANGED")
    if s.get("automatic_retry") is not False or s.get("no_orders") is not True:
        raise ValueError("SCOPE_BOUNDARY_INVALID")
    if int(s.get("maximum_requests",0))!=len(code_rows):
        raise ValueError("MAXIMUM_REQUESTS_MISMATCH")
    if Decimal(str(s.get("maximum_cost_cny","0")))!=PER_MEMBER_CAP*len(code_rows):
        raise ValueError("MAXIMUM_COST_MISMATCH")
    all_operational={x["code"]:x for x in select_operational_members(universe,policy)}
    for row in code_rows:
        if row.get("code") not in all_operational or row.get("universe_index")!=all_operational[row["code"]]["universe_index"]:
            raise ValueError("CODES_FILE_OUTSIDE_OPERATIONAL_POOL")
    cache_sha=hashlib.sha256(a.cache.read_bytes()).hexdigest()
    if cache_sha!=s["history_cache_sha256"]:
        raise ValueError("HISTORY_CACHE_SHA_MISMATCH")

    repo=Path(__file__).resolve().parents[1];scripts=repo/"scripts"
    safe_env={k:v for k,v in os.environ.items() if not any(z in k.upper() for z in ("SECRET","TOKEN","API_KEY","WEBHOOK","DSA_DRIVE"))}
    rows=[];provider_fail_streak=0;infra_fail_streak=0;stop_reason=None

    for member in code_rows:
        code=member["code"];row={
          "code":code,"universe_index":member["universe_index"],"status":"PENDING",
          "ranking_eligible":False,"strategy_core":None,"strategy_core_sha256":None,
          "raw_result_sha256":None,"narrative_release_status":None,"semantic_guards":[],
          "model_http_requests_confirmed":0,"model_http_requests_possible":0,
          "usage_peak_estimate_cny":"0","private_persistence":None,
        }
        if stop_reason:
            row["status"]="SKIPPED_AFTER_SHARED_STOP";row["failure_code"]=stop_reason;rows.append(row);continue
        root=a.out/code;root.mkdir();artifact=s["artifact_prefix"]+"-"+code;run_id=s["run_id"]+"-"+code
        claimed=False;provider_confirmed=False
        try:
            pre=root/"preflight"
            rc=command(
              scripts/"prepare_hk_o_operational_preflight_v3.py",
              ["--code",code,"--target",s["target_session"],"--universe",str(a.universe.resolve()),
               "--cache",str(a.cache.resolve()),"--policy",str(a.policy.resolve()),"--out",str(pre)],
              safe_env,root/"preflight.stdout"
            )
            if rc or not (pre/"preflight.json").exists():
                detail="FREE_PREFLIGHT_FAILED";pre_status=None
                if (pre/"FREE_PREFLIGHT_STATUS.json").exists():
                    ps=json.loads((pre/"FREE_PREFLIGHT_STATUS.json").read_text())
                    detail=ps.get("reason","") or detail;pre_status=ps.get("status")
                if pre_status=="SHARED_RUNTIME_FAILURE":
                    raise ValueError("SHARED_PREFLIGHT_RUNTIME_FAILURE:"+detail)
                row["status"]="EXCLUDED_PREFLIGHT_NO_RESCUE";row["failure_code"]=detail
                continue

            common=[
              "--symbol","HK"+code,"--checkout",str(a.checkout.resolve()),"--expected-commit",s["frozen_upstream"],
              "--preflight",str(pre/"preflight.json"),"--limit-cny","0.10","--carry-upper-cny","0",
              "--target-boundary-adapter","--news-handoff-v1","--frozen-native-history-adapter"
            ]
            env=dict(
              safe_env,
              DSA_DEEPSEEK_V41_TOKENIZER=os.environ["DSA_DEEPSEEK_V41_TOKENIZER"],
              LLM_CHANNELS="deepseek",LLM_DEEPSEEK_PROTOCOL="openai",LLM_DEEPSEEK_BASE_URL="https://api.deepseek.com",
              LLM_DEEPSEEK_MODELS="deepseek-flash",LITELLM_MODEL="openai/deepseek-flash",LITELLM_FALLBACK_MODELS="",
              REPORT_INTEGRITY_RETRY="0",MAX_WORKERS="1",DSA_INPUT_TOKEN_MARGIN="2048"
            )
            from o_native_model_configuration import configure
            env.update(configure(root,s["native_model_configuration"]))

            dry=root/"dry";dryenv=dict(env,DSA_BUDGET_PROBE_ONLY="1",LLM_DEEPSEEK_API_KEY="dry-envelope-no-network")
            command(scripts/"run_hk_original_model_probe_run030.py",[*common,"--output",str(dry)],dryenv,root/"dry.stdout")
            budget=json.loads((dry/"budget.json").read_text());req=budget.get("requests") or []
            if len(req)!=1 or req[0].get("status")!="dry_envelope_validated_not_sent":
                raise ValueError("FREE_NATIVE_ENVELOPE_FAILED")
            upper=Decimal(req[0]["pre_send_peak_upper_cny"])
            if upper>PER_MEMBER_CAP: raise ValueError("PRE_SEND_CAP_EXCEEDED")
            row["pre_send_upper_cny"]=str(upper)
            preflight_sha=hashlib.sha256((pre/"preflight.json").read_bytes()).hexdigest();row["preflight_sha256"]=preflight_sha

            row["pre_send_private_persistence"]=private_save(root,artifact+"-PRE-SEND",run_id)
            if not row["pre_send_private_persistence"].get("save_read_hash_restore"):
                raise StoreError("PRE_SEND_PRIVATE_SAVE_UNVERIFIED")
            available=balance()
            if available<PER_MEMBER_CAP:
                raise ValueError("BUDGET_OR_BALANCE_INSUFFICIENT")
            claim=reserve(artifact,run_id,preflight_sha,code);claimed=True;row["claim_persisted"]=True
            write(root/"private-claim.json",claim)

            actual=root/"native";actualenv=dict(env,DSA_BUDGET_PROBE_ONLY="0",LLM_DEEPSEEK_API_KEY=os.environ["DEEPSEEK_API_KEY"])
            rc=command(scripts/"run_hk_original_model_probe_run030.py",[*common,"--output",str(actual)],actualenv,root/"native.stdout")
            row["native_exit_code"]=rc
            b=json.loads((actual/"budget.json").read_text());requests=b.get("requests") or []
            row["model_http_requests_possible"]=len(requests)
            row["model_http_requests_confirmed"]=sum(x.get("status")=="response_received" for x in requests)
            provider_confirmed=row["model_http_requests_confirmed"]==1
            row["usage_peak_estimate_cny"]=str(sum(Decimal(x.get("usage_peak_estimate_cny",x["charge_upper_cny"])) for x in requests))
            row["usage"]=[x.get("usage") for x in requests]
            from o_provider_completion import inspect_completion
            completion=inspect_completion((actual/"provider-response.txt").read_bytes())
            write(actual/"provider-completion-audit.json",completion)
            row["provider_completion_status"]=completion["status"]
            row["provider_response_sha256"]=completion.get("raw_sha256")
            if completion["status"]!="PASS":
                row["status"]="PROVIDER_FAILED_NO_RETRY";row["failure_code"]="|".join(completion["blockers"])[:180]
                provider_fail_streak+=1
            else:
                core=evaluate_core(
                  json.loads((pre/"preflight.json").read_text()),
                  json.loads((actual/"original-input.json").read_text()),
                  json.loads((actual/"pipeline-final-result.json").read_text())
                )
                write(root/"strategy-core-receipt.json",core)
                row["ranking_eligible"]=core["ranking_eligible"]
                row["strategy_core"]=core["strategy_core"]
                row["strategy_core_sha256"]=core["strategy_core_sha256"]
                row["raw_result_sha256"]=core["raw_result_sha256"]
                row["narrative_release_status"]=core["narrative_release_status"]
                row["semantic_guards"]=core["semantic_guards"]
                row["core_blockers"]=core["blockers"]
                row["hard_semantic_count"]=len(core["hard_semantic_findings"])
                row["core_semantic_count"]=len(core["core_semantic_findings"])
                row["narrative_semantic_count"]=len(core["narrative_semantic_findings"])
                row["status"]="CORE_ACCEPTED" if core["ranking_eligible"] else "CORE_REJECTED_NO_RETRY"
                provider_fail_streak=0
            infra_fail_streak=0
        except Exception as exc:
            codeerr=_sanitize_failure(exc)
            row["failure_code"]=codeerr
            if not row.get("status") or row["status"]=="PENDING":
                row["status"]="EXCLUDED_AFTER_CLAIM_NO_RETRY" if claimed else "EXCLUDED_INFRA_OR_PREFLIGHT"
            if isinstance(exc,(StoreError,httpx.HTTPError)):
                infra_fail_streak+=1
            elif "BALANCE" in codeerr or "SHARED_PREFLIGHT_RUNTIME_FAILURE" in codeerr:
                infra_fail_streak=2
            else:
                infra_fail_streak=0
            if claimed and not provider_confirmed:
                row["model_http_requests_possible"]=max(1,row["model_http_requests_possible"])
        finally:
            try:
                write(root/"member-summary.json",row)
                row["private_persistence"]=private_save(root,artifact,run_id)
                if not row["private_persistence"].get("save_read_hash_restore"):
                    raise StoreError("FINAL_PRIVATE_SAVE_UNVERIFIED")
            except Exception as exc:
                row["ranking_eligible"]=False
                if row["status"]=="CORE_ACCEPTED": row["status"]="PRIVATE_FINAL_FAIL_NO_RETRY"
                row["private_persistence"]={"status":"FAIL","reason":_sanitize_failure(exc)}
                infra_fail_streak+=1
            rows.append(row)
            if provider_fail_streak>=s.get("max_consecutive_provider_failures",2):
                stop_reason="SHARED_STOP_PROVIDER_FAILURE_STREAK"
            if infra_fail_streak>=s.get("max_consecutive_infra_failures",2):
                stop_reason="SHARED_STOP_INFRA_FAILURE_STREAK"
            write(a.out/"SHARD_RESULT.json",{
              "schema_version":1,"run_id":s["run_id"],"shard_id":s.get("shard_id"),
              "target_session":s["target_session"],"members":rows,
              "attempted_members":sum(x["status"]!="SKIPPED_AFTER_SHARED_STOP" for x in rows),
              "core_accepted":sum(bool(x.get("ranking_eligible")) for x in rows),
              "model_http_requests_confirmed":sum(x.get("model_http_requests_confirmed",0) for x in rows),
              "usage_peak_estimate_cny":str(sum(Decimal(x.get("usage_peak_estimate_cny","0")) for x in rows)),
              "shared_stop_reason":stop_reason,"automatic_retry":False,"real_orders":0,
              "simulation_writes":0,"raw_content_public":False
            })
            print("O_OPERATIONAL_MEMBER "+json.dumps({
              "code":code,"status":row["status"],"ranking_eligible":row["ranking_eligible"],
              "score":(row.get("strategy_core") or {}).get("sentiment_score"),
              "action":(row.get("strategy_core") or {}).get("action"),
              "requests":row["model_http_requests_confirmed"],
            },ensure_ascii=False),flush=True)

    return 0


if __name__=="__main__":
    raise SystemExit(main())
