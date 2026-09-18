#!/usr/bin/env python3
"""Deterministic O-native strategy-core acceptance.

This layer does NOT repair or rewrite the frozen native model output. It separates
ranking-critical strategy fields from narrative/report fields so that unsupported
narrative claims can be quarantined without automatically discarding a valid
original O score/action.

The raw result remains immutable and private. Public output contains only a
minimal strategy-core receipt, semantic guard IDs/paths, and hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from o_single_output_fact_check import check_saved_output

VERSION = "O_STRATEGY_CORE_ACCEPTANCE_v1"
FROZEN_UPSTREAM = "089d9d26d68f8b839ea5a74a3784e4402925f8b7"

CORE_FIELDS = (
    "action",
    "sentiment_score",
    "decision_type",
    "operation_advice",
    "guardrail_reason",
)
ALLOWED_ACTIONS = {"buy","add","hold","reduce","sell","watch","avoid","alert"}
ACTION_FAMILY = {
    "buy":"buy","add":"buy",
    "hold":"hold","watch":"hold","avoid":"hold",
    "reduce":"sell","sell":"sell","alert":"sell",
}


def canonical_json_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False).encode()
    ).hexdigest()


def _num(value):
    if value is None or isinstance(value,bool):
        return None
    try:
        x=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        return None
    return x if x.is_finite() else None


def _guardrail_reason(result: dict) -> str | None:
    dashboard=result.get("dashboard") if isinstance(result.get("dashboard"),dict) else {}
    stability=dashboard.get("decision_stability") if isinstance(dashboard.get("decision_stability"),dict) else {}
    candidates=[
        result.get("guardrail_reason"),
        result.get("downgrade_reason"),
        result.get("decision_score_guardrail_reason"),
    ]
    if stability.get("applied") not in (False,0,"0","false","False"):
        candidates += [
            stability.get("guardrail_reason"),
            stability.get("downgrade_reason"),
            stability.get("reason"),
        ]
    for item in candidates:
        text=str(item or "").strip()
        if text:
            return text
    return None


def _score_family(score: Decimal) -> str:
    if score >= 60:
        return "buy"
    if score >= 40:
        return "hold"
    return "sell"


def _core_path(path: str) -> bool:
    p=str(path or "").lstrip("$").lstrip(".")
    return any(p==f or p.startswith(f+".") or p.startswith(f+"[") for f in CORE_FIELDS)


def evaluate(preflight: dict, original_input: dict, result: dict) -> dict:
    before=canonical_json_hash(result)
    audit=check_saved_output(preflight,original_input,result)
    findings=audit.get("findings") or []
    blockers=[]

    if result.get("success") is False or result.get("error_message"):
        blockers.append("NATIVE_ANALYSIS_FAILED")

    score=_num(result.get("sentiment_score"))
    if score is None or score < 0 or score > 100:
        blockers.append("INVALID_SENTIMENT_SCORE")

    action=str(result.get("action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        blockers.append("INVALID_ACTION")

    decision_type=str(result.get("decision_type") or "").strip().lower() or None
    if decision_type not in (None,"buy","hold","sell"):
        blockers.append("INVALID_DECISION_TYPE")

    guardrail=_guardrail_reason(result)
    if score is not None and 0 <= score <= 100 and action in ALLOWED_ACTIONS:
        family=ACTION_FAMILY[action]
        score_family=_score_family(score)
        if family != score_family and not guardrail:
            blockers.append("SCORE_ACTION_CONFLICT_WITHOUT_GUARDRAIL")
        if decision_type is not None and decision_type != family:
            blockers.append("ACTION_DECISION_TYPE_CONFLICT")

    hard_semantic=[]
    core_semantic=[]
    narrative_semantic=[]
    for finding in findings:
        row={
            "code":finding.get("code"),
            "guard_id":finding.get("guard_id"),
            "severity":finding.get("severity"),
            "paths":finding.get("paths") or [],
        }
        if finding.get("severity")=="BLOCK":
            hard_semantic.append(row)
        elif any(_core_path(path) for path in row["paths"]):
            core_semantic.append(row)
        else:
            narrative_semantic.append(row)

    if hard_semantic:
        blockers.append("HARD_SEMANTIC_BLOCK")
    if core_semantic:
        blockers.append("CORE_FIELD_SEMANTIC_BLOCK")

    accepted=not blockers
    score_out=float(score) if score is not None else None
    if score is not None and score == score.to_integral_value():
        score_out=int(score)

    core={
        "action": action if action in ALLOWED_ACTIONS else None,
        "sentiment_score": score_out,
        "decision_type": decision_type,
        "action_family": ACTION_FAMILY.get(action),
        "score_family": _score_family(score) if score is not None and 0 <= score <= 100 else None,
        "guardrail_reason_present": bool(guardrail),
    }
    receipt={
        "schema_version":1,
        "version":VERSION,
        "frozen_upstream":FROZEN_UPSTREAM,
        "status":"CORE_ACCEPTED" if accepted else "CORE_REJECTED",
        "ranking_eligible":accepted,
        "narrative_release_status":"PASS" if not narrative_semantic else "QUARANTINED",
        "strategy_core":core,
        "strategy_core_sha256":canonical_json_hash(core),
        "raw_result_sha256":before,
        "semantic_verdict":audit.get("semantic_verdict"),
        "semantic_guards":audit.get("triggered_semantic_guards") or [],
        "hard_semantic_findings":hard_semantic,
        "core_semantic_findings":core_semantic,
        "narrative_semantic_findings":narrative_semantic,
        "blockers":sorted(set(blockers)),
        "raw_result_mutated":canonical_json_hash(result)!=before,
        "model_requests_added":0,
        "strategy_fields_rewritten":False,
    }
    if receipt["raw_result_mutated"]:
        raise AssertionError("RAW_RESULT_MUTATED")
    return receipt


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--preflight",type=Path,required=True)
    ap.add_argument("--original-input",type=Path,required=True)
    ap.add_argument("--result",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    r=evaluate(
        json.loads(a.preflight.read_text(encoding="utf-8")),
        json.loads(a.original_input.read_text(encoding="utf-8")),
        json.loads(a.result.read_text(encoding="utf-8")),
    )
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":r["status"],
        "ranking_eligible":r["ranking_eligible"],
        "score":r["strategy_core"]["sentiment_score"],
        "action":r["strategy_core"]["action"],
        "narrative_release_status":r["narrative_release_status"],
        "blockers":r["blockers"],
    },ensure_ascii=False))


if __name__=="__main__":
    main()
