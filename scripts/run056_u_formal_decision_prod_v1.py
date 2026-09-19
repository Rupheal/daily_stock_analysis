#!/usr/bin/env python3
"""Production wrapper for the accepted U45 formal decision engine.

Keeps historical Run056 defaults untouched while injecting a new target session,
run identity and session-scoped Drive artifact prefix. Strategy prompt, score
semantics, response validation and two-batch provider execution are inherited
from the accepted Run056 implementation.

No Entry-v1, broker order, fill or simulation write occurs here.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

import run056_u_formal_decision_v2 as compat

base=compat.base


def configure(target_session:str,run_id:str):
    if not target_session or len(target_session)!=10:
        raise ValueError("PROD_U_TARGET_SESSION_INVALID")
    if not run_id or len(run_id)>120:
        raise ValueError("PROD_U_RUN_ID_INVALID")
    base.TARGET_SESSION=target_session
    base.EXPECTED_RUN_ID=run_id
    base.ARTIFACT_PREFIX="DSA-U-PROD-"+target_session.replace("-","")
    return {
      "target_session":target_session,
      "run_id":run_id,
      "artifact_prefix":base.ARTIFACT_PREFIX,
      "strategy_version":base.VERSION,
      "model":base.MODEL,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--target-session",required=True)
    ap.add_argument("--run-id",required=True)
    ap.add_argument("--scope",type=Path,required=True)
    ap.add_argument("--member",type=Path,required=True)
    ap.add_argument("--close",type=Path,required=True)
    ap.add_argument("--macro",type=Path,required=True)
    ap.add_argument("--risk",type=Path,required=True)
    ap.add_argument("--zone",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    cfg=configure(a.target_session,a.run_id)
    scope=json.loads(a.scope.read_text())
    scope=dict(scope)
    scope["run_id"]=a.run_id
    # Production session remains two provider requests max; no auto recharge.
    scope["maximum_requests"]=2
    if "provider_plan" in scope:
        scope["provider_plan"]=dict(scope["provider_plan"])
        scope["provider_plan"]["maximum_requests"]=2
    temp=a.out.parent/(a.out.name+".scope.json")
    temp.parent.mkdir(parents=True,exist_ok=True)
    temp.write_text(json.dumps(scope,ensure_ascii=False,indent=2)+"\n")
    sys.argv=[
      "run056_u_formal_decision_prod_v1.py",
      "--scope",str(temp),
      "--member",str(a.member),
      "--close",str(a.close),
      "--macro",str(a.macro),
      "--risk",str(a.risk),
      "--zone",str(a.zone),
      "--out",str(a.out),
    ]
    base.main()
    result=json.loads((a.out/"SANITIZED_U_FORMAL_RESULT.json").read_text())
    if result.get("target_session")!=a.target_session or result.get("run_id")!=a.run_id:
        raise ValueError("PROD_U_RESULT_IDENTITY_MISMATCH")
    print(json.dumps({
      "production_wrapper":"PASS",
      "target_session":a.target_session,
      "run_id":a.run_id,
      "state":result.get("state"),
      "qualified_BUY":result.get("qualified_BUY"),
      "real_orders":result.get("resource_accounting",{}).get("real_orders",0),
    },ensure_ascii=False))


if __name__=="__main__":
    main()
