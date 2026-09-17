"""Pool-native preflight v2: prior-adjudicated history + fresh target-session check.

Historical cross-provider differences are *not* silently accepted. They are
reported as diagnostics and the code is eligible only if Run057 already placed
it in the deterministic-ready set after Run050-052 adjudication. The fresh
preflight then independently checks the target session and binds every native
history byte for the downstream input contract.

No model call, no trading signal, and no claim of complete news coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests

from prepare_hk_pool_rollout_preflight import (
    atomic_json,
    normalize_native,
    tencent_rows,
    OHLC_TOLERANCE,
    LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
    CALIBRATION_RUN_ID,
    UNIT_SEMANTICS,
)


def _historical_diagnostic(native, independent):
    by={x["date"]:x for x in independent}
    mismatches=[]
    for left in native:
        right=by.get(left["date"])
        if not right:
            continue
        fields=[]
        for key in ("open","high","low","close"):
            delta=abs(float(left[key])-float(right[key]))
            if delta>OHLC_TOLERANCE+1e-9:
                fields.append({"field":key,"delta":delta})
        if fields:
            mismatches.append({"date":left["date"],"fields":fields})
    return {
        "overlap_sessions":sum(1 for x in native if x["date"] in by),
        "ohlc_mismatch_sessions":len(mismatches),
        "first_mismatch":mismatches[0] if mismatches else None,
        "last_mismatch":mismatches[-1] if mismatches else None,
        "admission_use":"INFORMATIONAL_ONLY_PRIOR_RUN050_052_ADJUDICATION_CONTROLS_HISTORY",
    }


def _fresh_target_check(native, independent, target):
    by={x["date"]:x for x in independent}
    left=native[-1]
    right=by.get(target)
    if left["date"]!=target or right is None:
        raise ValueError("TARGET_SESSION_INDEPENDENT_MISSING")
    fields={}
    for key in ("open","high","low","close"):
        delta=abs(float(left[key])-float(right[key]))
        fields[key]={"native":left[key],"tencent":right[key],"delta":delta}
        if delta>OHLC_TOLERANCE+1e-9:
            raise ValueError("TARGET_SESSION_OHLC_DISAGREEMENT")
    lv,rv=float(left["volume"]),float(right["volume"])
    if lv==0 or rv==0:
        if lv!=rv:
            raise ValueError("TARGET_SESSION_VOLUME_ZERO_MISMATCH")
        deviation=0.0;status="exact"
    else:
        deviation=abs(lv/rv-1.0)
        if lv==rv:
            status="exact"
        elif deviation<=LATEST_VOLUME_MAX_RELATIVE_DEVIATION+1e-12:
            status="bounded_provider_reconciliation"
        else:
            raise ValueError("TARGET_SESSION_VOLUME_OUTSIDE_CALIBRATED_BOUND")
    return {
        "target_session":target,
        "ohlc_absolute_tolerance":OHLC_TOLERANCE,
        "ohlc":fields,
        "volume":{
            "calibration_run_id":CALIBRATION_RUN_ID,
            "latest_session_max_relative_deviation":LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
            "unit_semantics":UNIT_SEMANTICS,
            "latest_relative_deviation":deviation,
            "latest_status":status,
        },
    }


def build_preflight(code,target,universe,cache,plan,independent,source):
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts

    member=next((x for x in universe["members"] if x["code"]==code),None)
    if member is None or not member.get("channels") or not universe.get("full_union_verified"):
        raise ValueError("OFFICIAL_UNIVERSE_IDENTITY_UNVERIFIED")
    if cache.get("target_session")!=target:
        raise ValueError("NATIVE_CACHE_TARGET_MISMATCH")
    if plan.get("target_session")!=target or plan.get("state")!="PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN":
        raise ValueError("RUN057_PLAN_NOT_ACCEPTED")
    ready=set((plan.get("rollout") or {}).get("ready_codes") or [])
    isolated=set((plan.get("isolation") or {}).get("codes") or [])
    if code not in ready or code in isolated:
        raise ValueError("CODE_NOT_PRIOR_ADJUDICATED_READY")
    required_receipts=("docs/runtime/RUN050_O_SESSION_LISTING_ADJUDICATION.json",
                       "docs/runtime/RUN051_O_THIRD_SOURCE_ADJUDICATION.json",
                       "docs/runtime/RUN052_O_GEOMETRY_ADJUDICATION.json")
    ih=plan.get("input_sha256") or {}
    if any(not isinstance(ih.get(p),str) or len(ih[p])!=64 for p in required_receipts):
        raise ValueError("PRIOR_ADJUDICATION_HASHES_MISSING")

    raw=(cache.get("histories") or {}).get("hk"+code)
    if raw is None:
        raise ValueError("NATIVE_CACHE_MEMBER_MISSING")
    native=normalize_native(raw,target)
    fresh=_fresh_target_check(native,independent,target)
    histdiag=_historical_diagnostic(native,independent)
    if histdiag["overlap_sessions"]<21:
        raise ValueError("INDEPENDENT_OVERLAP_LT_21")

    today=dict(native[-1]);yesterday=dict(native[-2])
    for row in (today,yesterday):
        if row.get("amount") is not None:
            try:
                if not math.isfinite(float(row["amount"])):row["amount"]=None
            except (TypeError,ValueError):
                row["amount"]=None
    context={"date":target,"today":today,"yesterday":yesterday,
             "volume_change_ratio":round(today["volume"]/yesterday["volume"],2) if yesterday["volume"] else None}
    validate_daily_context(context,target)
    now=datetime.now(timezone.utc).isoformat()

    preflight={
        "passed":True,
        "symbol":"HK"+code,
        "stock_name":member["official_name"],
        "prices_passed":True,
        "prepared_at":now,
        "target":target,
        "today":today,
        "yesterday":yesterday,
        "facts":daily_consistency_facts(context),
        "price_reconciliation":{
            "overlap_sessions":histdiag["overlap_sessions"],
            "ohlc_absolute_tolerance":OHLC_TOLERANCE,
            "independent_provider":"Tencent HK qfq daily",
            "fresh_target_session":fresh,
            "historical_cross_provider_diagnostic":histdiag,
            "historical_admission_basis":"RUN050_052_PRIOR_ADJUDICATION_PLUS_IMMUTABLE_NATIVE_HISTORY_BINDING",
            "volume":fresh["volume"],
        },
        "overlap":histdiag["overlap_sessions"],
        "validated_native_history":native,
        "native_history_window":{
            "first":native[0]["date"],"last":target,"count":len(native),
            "scope":"Immutable native history bound byte-for-byte downstream; prior Run050-052 controls historical admission; fresh Tencent independently validates target-session OHLC and calibrated volume.",
            "ma60_supported":len(native)>=60,
        },
        "component_status":{"prices":"passed","news":"passed_limited_coverage"},
        "news_count":0,
        "news_count_semantics":"ADMITTED_SOURCE_URL_COUNT_NOT_SEARCH_RESULT_COUNT",
        "news_search_performed":False,
        "allowed_news_urls":[],
        "company_news_evidence":[],
        "execution_contract":{
            "version":"O_GATE_A_EXECUTION_CONTRACT_v2",
            "realtime_quote_available":False,
            "target_session":target,
            "session_fact_anchor_required":True,
        },
        "hk_report_contract":{"required_risk_ids":[]},
        "risk_review_complete":False,
        "limitation":"No issuer/news item is admitted. This is not evidence that no negative news exists. Historical Tencent-vs-native adjusted-price differences are disclosed but not re-adjudicated here because Run057 explicitly binds accepted Run050-052 adjudication; the fresh target session is independently rechecked.",
        "sources":{
            "universe_sha256":universe["_sha256"],
            "native_cache_sha256":cache["_sha256"],
            "run057_plan_sha256":plan["_sha256"],
            "prior_historical_adjudication_sha256":{p:ih[p] for p in required_receipts},
            "independent_tencent":source,
        },
    }
    json.dumps(preflight,allow_nan=False,default=str)
    return preflight


def prepare(code,target,universe_path,cache_path,plan_path,out):
    ub=universe_path.read_bytes();cb=cache_path.read_bytes();pb=plan_path.read_bytes()
    universe=json.loads(ub);cache=json.loads(cb);plan=json.loads(pb)
    universe["_sha256"]=hashlib.sha256(ub).hexdigest()
    cache["_sha256"]=hashlib.sha256(cb).hexdigest()
    plan["_sha256"]=hashlib.sha256(pb).hexdigest()
    response=requests.get("https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
                          params={"param":f"hk{code},day,,,180,qfq"},timeout=(8,18))
    response.raise_for_status()
    independent=tencent_rows(response.json(),code,target)
    source={"provider":"Tencent HK qfq daily","url":response.url,
            "retrieved_at":datetime.now(timezone.utc).isoformat(),
            "sha256":hashlib.sha256(response.content).hexdigest()}
    preflight=build_preflight(code,target,universe,cache,plan,independent,source)
    out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/"preflight.json",preflight)
    atomic_json(out/"independent-source.json",source)
    return {"symbol":"HK"+code,"status":"PASS_POOL_TARGET_PREFLIGHT_V2","target":target,
            "overlap":preflight["overlap"],"historical_mismatch_sessions":preflight["price_reconciliation"]["historical_cross_provider_diagnostic"]["ohlc_mismatch_sessions"],
            "model_requests":0,"news_admitted":0}


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--code",required=True);ap.add_argument("--target",required=True)
    ap.add_argument("--universe",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--plan",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    try:
        print(json.dumps(prepare(a.code,a.target,a.universe,a.cache,a.plan,a.out),ensure_ascii=False))
    except Exception as exc:
        import re
        reason=str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_ :.-]{2,180}",str(exc)) else type(exc).__name__
        a.out.mkdir(parents=True,exist_ok=True)
        atomic_json(a.out/"FREE_PREFLIGHT_STATUS.json",{"status":"FAILED","reason":reason,"model_requests":0})
        raise
