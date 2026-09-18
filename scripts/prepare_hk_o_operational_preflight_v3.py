#!/usr/bin/env python3
"""Current-session O operational-pool preflight v3.

Uses the latest official universe + frozen native history + the explicit
unresolved-symbol exclusion policy. It does not depend on the older Run057
608-member adjudication plan. One normal refresh (Run060) plus this independent
Tencent target-session check is the bounded confirmation allowed by policy.

No model call, no retry loop, no signal.
"""
from __future__ import annotations
import argparse,hashlib,json,math,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import requests

from prepare_hk_pool_rollout_preflight import (
    atomic_json, normalize_native, tencent_rows,
    OHLC_TOLERANCE, LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
    CALIBRATION_RUN_ID, UNIT_SEMANTICS,
)


def fresh_target_check(native, independent, target):
    by={x["date"]:x for x in independent}
    left=native[-1];right=by.get(target)
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
        if lv!=rv: raise ValueError("TARGET_SESSION_VOLUME_ZERO_MISMATCH")
        deviation=0.0;status="exact"
    else:
        deviation=abs(lv/rv-1.0)
        if lv==rv: status="exact"
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


def build_preflight(code,target,universe,cache,policy,independent,source):
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts
    cur=policy.get("current_session") or {}
    if cur.get("session")!=target:
        raise ValueError("EXCLUSION_POLICY_SESSION_MISMATCH")
    if cur.get("official_denominator")!=660:
        raise ValueError("OFFICIAL_DENOMINATOR_CHANGED")
    excluded={x.get("code") for x in cur.get("excluded_unresolved") or []}
    if code in excluded:
        raise ValueError("POLICY_EXCLUDED_UNRESOLVED")
    member=next((x for x in universe.get("members",[]) if x.get("code")==code),None)
    if member is None or not member.get("channels") or not universe.get("full_union_verified"):
        raise ValueError("OFFICIAL_UNIVERSE_IDENTITY_UNVERIFIED")
    if len(universe.get("members") or [])!=660:
        raise ValueError("OFFICIAL_UNIVERSE_COUNT_MISMATCH")
    if cache.get("target_session")!=target:
        raise ValueError("NATIVE_CACHE_TARGET_MISMATCH")
    raw=(cache.get("histories") or {}).get("hk"+code)
    if raw is None:
        raise ValueError("NATIVE_CACHE_MEMBER_MISSING")
    native=normalize_native(raw,target)
    if len(native)<21:
        raise ValueError("NATIVE_HISTORY_LT_21")
    fresh=fresh_target_check(native,independent,target)
    today=dict(native[-1]);yesterday=dict(native[-2])
    for row in (today,yesterday):
        if row.get("amount") is not None:
            try:
                if not math.isfinite(float(row["amount"])): row["amount"]=None
            except (TypeError,ValueError): row["amount"]=None
    context={"date":target,"today":today,"yesterday":yesterday,
             "volume_change_ratio":round(today["volume"]/yesterday["volume"],2) if yesterday["volume"] else None}
    validate_daily_context(context,target)
    return {
      "passed":True,
      "symbol":"HK"+code,
      "stock_name":member["official_name"],
      "prices_passed":True,
      "prepared_at":datetime.now(timezone.utc).isoformat(),
      "target":target,
      "today":today,
      "yesterday":yesterday,
      "facts":daily_consistency_facts(context),
      "price_reconciliation":{
        "independent_provider":"Tencent HK qfq daily",
        "fresh_target_session":fresh,
        "historical_admission_basis":"RUN060_CURRENT_NATIVE_CACHE_PLUS_POLICY_BOUNDED_TARGET_CONFIRMATION",
        "volume":fresh["volume"],
      },
      "overlap":len(native),
      "validated_native_history":native,
      "native_history_window":{
        "first":native[0]["date"],"last":target,"count":len(native),
        "scope":"Run060 current-session native cache bound downstream; one independent target-session confirmation; no bespoke rescue loop.",
        "ma60_supported":len(native)>=60,
      },
      "component_status":{"prices":"passed","news":"passed_limited_coverage"},
      "news_count":0,
      "news_count_semantics":"NO_ADMITTED_ISSUER_NEWS_IN_THIS_O_CORE_RANKING_PREFLIGHT",
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
      "limitation":"O strategy-core ranking preflight. Narrative absence-of-bad-news claims remain quarantinable. This is not a claim of complete issuer/news risk coverage.",
      "operational_pool":{
        "policy_id":policy.get("policy_id"),
        "official_denominator":cur.get("official_denominator"),
        "base_operational_denominator":cur.get("operational_denominator"),
        "base_excluded_count":cur.get("excluded_count"),
      },
      "sources":{
        "universe_sha256":universe["_sha256"],
        "native_cache_sha256":cache["_sha256"],
        "exclusion_policy_sha256":policy["_sha256"],
        "independent_tencent":source,
      },
    }


def prepare(code,target,universe_path,cache_path,policy_path,out):
    ub=universe_path.read_bytes();cb=cache_path.read_bytes();pb=policy_path.read_bytes()
    universe=json.loads(ub);cache=json.loads(cb);policy=json.loads(pb)
    universe["_sha256"]=hashlib.sha256(ub).hexdigest()
    cache["_sha256"]=hashlib.sha256(cb).hexdigest()
    policy["_sha256"]=hashlib.sha256(pb).hexdigest()
    response=requests.get(
      "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
      params={"param":f"hk{code},day,,,180,qfq"},timeout=(8,18)
    )
    response.raise_for_status()
    independent=tencent_rows(response.json(),code,target)
    source={"provider":"Tencent HK qfq daily","url":response.url,
            "retrieved_at":datetime.now(timezone.utc).isoformat(),
            "sha256":hashlib.sha256(response.content).hexdigest()}
    pf=build_preflight(code,target,universe,cache,policy,independent,source)
    out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/"preflight.json",pf)
    atomic_json(out/"independent-source.json",source)
    return {"symbol":"HK"+code,"status":"PASS_O_OPERATIONAL_PREFLIGHT_V3","target":target,"model_requests":0}


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--code",required=True);ap.add_argument("--target",required=True)
    ap.add_argument("--universe",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--policy",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    try:
        print(json.dumps(prepare(a.code,a.target,a.universe,a.cache,a.policy,a.out),ensure_ascii=False))
    except Exception as exc:
        import re
        shared=isinstance(exc,ModuleNotFoundError)
        if shared:
            reason="MODULE_DEPENDENCY_MISSING:"+str(getattr(exc,"name",None) or "UNKNOWN")
        else:
            reason=str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_ :.-]{2,180}",str(exc)) else type(exc).__name__
        a.out.mkdir(parents=True,exist_ok=True)
        atomic_json(a.out/"FREE_PREFLIGHT_STATUS.json",{
          "status":"SHARED_RUNTIME_FAILURE" if shared else "EXCLUDE_UNRESOLVED_FOR_SESSION",
          "reason":reason,"model_requests":0,"repeat_rescue":False
        })
        raise
