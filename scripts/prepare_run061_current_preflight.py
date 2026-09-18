"""Run061 current-session O preflight for a Run057 rollout member.

Historical/no-repeat admission is inherited from immutable Run057. Current-session
identity and native history come from Run060. Fresh Tencent target-session evidence
is re-fetched now. This module is zero-model and never touches Drive claims.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
import requests

from prepare_hk_pool_rollout_preflight import (
    atomic_json, normalize_native, tencent_rows,
    OHLC_TOLERANCE, LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
    CALIBRATION_RUN_ID, UNIT_SEMANTICS,
)

def _hist_diag(native, independent):
    by={x["date"]:x for x in independent}; mismatches=[]
    for left in native:
        right=by.get(left["date"])
        if not right: continue
        fs=[]
        for k in ("open","high","low","close"):
            d=abs(float(left[k])-float(right[k]))
            if d>OHLC_TOLERANCE+1e-9: fs.append({"field":k,"delta":d})
        if fs:mismatches.append({"date":left["date"],"fields":fs})
    return {
      "overlap_sessions":sum(1 for x in native if x["date"] in by),
      "ohlc_mismatch_sessions":len(mismatches),
      "first_mismatch":mismatches[0] if mismatches else None,
      "last_mismatch":mismatches[-1] if mismatches else None,
      "admission_use":"INFORMATIONAL_ONLY_RUN057_HISTORICAL_ADJUDICATION_REMAINS_BINDING",
    }

def _target(native, independent, target):
    by={x["date"]:x for x in independent}
    left=native[-1]; right=by.get(target)
    if left["date"]!=target or right is None: raise ValueError("TARGET_SESSION_INDEPENDENT_MISSING")
    fields={}
    for k in ("open","high","low","close"):
        d=abs(float(left[k])-float(right[k]))
        fields[k]={"native":left[k],"tencent":right[k],"delta":d}
        if d>OHLC_TOLERANCE+1e-9: raise ValueError("TARGET_SESSION_OHLC_DISAGREEMENT")
    lv,rv=float(left["volume"]),float(right["volume"])
    if lv==0 or rv==0:
        if lv!=rv: raise ValueError("TARGET_SESSION_VOLUME_ZERO_MISMATCH")
        dev=0.0;status="exact"
    else:
        dev=abs(lv/rv-1.0)
        if lv==rv:status="exact"
        elif dev<=LATEST_VOLUME_MAX_RELATIVE_DEVIATION+1e-12:status="bounded_provider_reconciliation"
        else:raise ValueError("TARGET_SESSION_VOLUME_OUTSIDE_CALIBRATED_BOUND")
    return {"target_session":target,"ohlc":fields,"ohlc_absolute_tolerance":OHLC_TOLERANCE,
      "volume":{"calibration_run_id":CALIBRATION_RUN_ID,
      "latest_session_max_relative_deviation":LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
      "unit_semantics":UNIT_SEMANTICS,"latest_relative_deviation":dev,"latest_status":status}}

def build(code,target,universe,cache,plan,independent,source):
    from src.services.market_data_integrity import validate_daily_context,daily_consistency_facts
    member=next((x for x in universe["members"] if x["code"]==code),None)
    if member is None or not member.get("channels") or not universe.get("full_union_verified"):
        raise ValueError("OFFICIAL_UNIVERSE_IDENTITY_UNVERIFIED")
    if cache.get("target_session")!=target: raise ValueError("RUN060_CACHE_TARGET_MISMATCH")
    if plan.get("state")!="PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN": raise ValueError("RUN057_PLAN_NOT_ACCEPTED")
    if plan.get("target_session")!="2026-09-17": raise ValueError("RUN057_HISTORICAL_PLAN_TARGET_UNEXPECTED")
    ready=set((plan.get("rollout") or {}).get("ready_codes") or [])
    never=set((plan.get("rollout") or {}).get("never_called_codes") or [])
    isolated=set((plan.get("isolation") or {}).get("codes") or [])
    if code not in ready or code not in never or code in isolated: raise ValueError("CODE_NOT_RUN057_NEVER_CALLED_READY")
    raw=(cache.get("histories") or {}).get("hk"+code)
    if raw is None: raise ValueError("RUN060_NATIVE_CACHE_MEMBER_MISSING")
    native=normalize_native(raw,target)
    if len(native)<21: raise ValueError("NATIVE_HISTORY_LT_21")
    # Geometry on the exact current native window.
    for r in native:
        vals=[float(r[k]) for k in ("open","high","low","close","volume")]
        if any(not math.isfinite(x) for x in vals): raise ValueError("NATIVE_HISTORY_NONFINITE")
        o,h,l,c,v=vals
        if v<0 or h+1e-12<max(o,c) or l-1e-12>min(o,c) or h<l: raise ValueError("INVALID_BAR_GEOMETRY")
    fresh=_target(native,independent,target)
    diag=_hist_diag(native,independent)
    if diag["overlap_sessions"]<21: raise ValueError("INDEPENDENT_OVERLAP_LT_21")
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
      "passed":True,"prices_passed":True,"symbol":"HK"+code,"stock_name":member["official_name"],
      "prepared_at":datetime.now(timezone.utc).isoformat(),"target":target,
      "today":today,"yesterday":yesterday,"facts":daily_consistency_facts(context),
      "validated_native_history":native,
      "native_history_window":{"first":native[0]["date"],"last":target,"count":len(native),
        "scope":"Run060 current-session native history; Run057 historical/no-repeat admission retained."},
      "price_reconciliation":{"volume":fresh["volume"],"fresh_target_session":fresh,
        "historical_cross_provider_diagnostic":diag,
        "historical_admission_basis":"RUN057_IMMUTABLE_PLAN_PLUS_RUN060_CURRENT_HISTORY"},
      "overlap":diag["overlap_sessions"],
      "component_status":{"prices":"passed","news":"passed_limited_coverage"},
      "news_count":0,"news_count_semantics":"ADMITTED_SOURCE_URL_COUNT_NOT_SEARCH_RESULT_COUNT",
      "news_search_performed":False,"allowed_news_urls":[],"company_news_evidence":[],
      "execution_contract":{"version":"O_GATE_A_EXECUTION_CONTRACT_v3_CURRENT_SESSION",
        "realtime_quote_available":False,"target_session":target,"session_fact_anchor_required":True},
      "hk_report_contract":{"required_risk_ids":[]},"risk_review_complete":False,
      "limitation":"No issuer/news item admitted. Run057 historical adjudication is not repeated; Run060 current session is freshly independently checked.",
      "sources":{"run060_universe_sha256":universe["_sha256"],"run060_native_cache_sha256":cache["_sha256"],
        "run057_plan_sha256":plan["_sha256"],"independent_tencent":source},
    }

def prepare(code,target,universe_path,cache_path,plan_path,out):
    ub=universe_path.read_bytes();cb=cache_path.read_bytes();pb=plan_path.read_bytes()
    u=json.loads(ub);c=json.loads(cb);p=json.loads(pb)
    u["_sha256"]=hashlib.sha256(ub).hexdigest();c["_sha256"]=hashlib.sha256(cb).hexdigest();p["_sha256"]=hashlib.sha256(pb).hexdigest()
    response=requests.get("https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
      params={"param":f"hk{code},day,,,180,qfq"},timeout=(8,18))
    response.raise_for_status()
    independent=tencent_rows(response.json(),code,target)
    source={"provider":"Tencent HK qfq daily","url":response.url,
      "retrieved_at":datetime.now(timezone.utc).isoformat(),"sha256":hashlib.sha256(response.content).hexdigest()}
    pre=build(code,target,u,c,p,independent,source)
    out.mkdir(parents=True,exist_ok=False);atomic_json(out/"preflight.json",pre);atomic_json(out/"independent-source.json",source)
    return {"code":code,"status":"PASS_CURRENT_TARGET_PREFLIGHT","target":target,"history_count":len(pre["validated_native_history"]),
      "target_volume_status":pre["price_reconciliation"]["fresh_target_session"]["volume"]["latest_status"],
      "model_http_requests":0}

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--code",required=True);ap.add_argument("--target",required=True)
    ap.add_argument("--universe",type=Path,required=True);ap.add_argument("--cache",type=Path,required=True)
    ap.add_argument("--plan",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    try: print(json.dumps(prepare(a.code,a.target,a.universe,a.cache,a.plan,a.out),ensure_ascii=False))
    except Exception as exc:
        import re
        reason=str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_ :.-]{2,180}",str(exc)) else type(exc).__name__
        a.out.mkdir(parents=True,exist_ok=True)
        atomic_json(a.out/"FREE_PREFLIGHT_STATUS.json",{"status":"FAILED","reason":reason,"model_requests":0})
        raise
