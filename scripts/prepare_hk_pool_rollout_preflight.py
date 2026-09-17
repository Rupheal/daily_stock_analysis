"""Full-pool O native preflight from the accepted native market-history cache.

This is a deterministic/free input gate. It does not call the model, does not
claim complete news coverage and does not create a trading signal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests

OHLC_TOLERANCE = 0.005
LATEST_VOLUME_MAX_RELATIVE_DEVIATION = 0.00170985
CALIBRATION_RUN_ID = 34983641578
UNIT_SEMANTICS = "same-scale empirically verified; no 100x/0.01x pattern in calibration"


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError("INVALID_" + label)
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError("INVALID_" + label) from None
    if not math.isfinite(x):
        raise ValueError("INVALID_" + label)
    return x


def normalize_native(rows, target):
    out = []
    for source in rows:
        row = {k: source.get(k) for k in (
            "date", "open", "high", "low", "close", "volume", "amount",
            "pct_chg", "ma5", "ma10", "ma20", "volume_ratio", "data_source"
        )}
        row["date"] = str(row["date"])[:10]
        if row["date"] > target:
            raise ValueError("FUTURE_BAR_IN_NATIVE_CACHE")
        for key in ("open", "high", "low", "close", "volume"):
            row[key] = _number(row[key], "NATIVE_" + key.upper())
        if not (0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]):
            raise ValueError("INVALID_NATIVE_BAR_GEOMETRY")
        if row["volume"] < 0:
            raise ValueError("INVALID_NATIVE_VOLUME")
        out.append(row)
    dates = [x["date"] for x in out]
    if dates != sorted(set(dates)):
        raise ValueError("DUPLICATE_OR_UNSORTED_NATIVE_HISTORY")
    if len(out) < 21:
        raise ValueError("NATIVE_HISTORY_LT_21")
    if dates[-1] != target:
        raise ValueError("NATIVE_TARGET_MISSING")
    return out


def tencent_rows(payload, code, target):
    item = (payload.get("data") or {}).get("hk" + code)
    if not isinstance(item, dict):
        raise ValueError("TENCENT_SYMBOL_MISSING")
    raw = item.get("qfqday") or item.get("day") or []
    out = []
    for vals in raw:
        if not vals or str(vals[0])[:10] > target:
            continue
        if len(vals) < 6:
            raise ValueError("TENCENT_ROW_SHORT")
        row = {
            "date": str(vals[0])[:10],
            "open": _number(vals[1], "TENCENT_OPEN"),
            "close": _number(vals[2], "TENCENT_CLOSE"),
            "high": _number(vals[3], "TENCENT_HIGH"),
            "low": _number(vals[4], "TENCENT_LOW"),
            "volume": _number(vals[5], "TENCENT_VOLUME"),
        }
        if not (0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]):
            raise ValueError("INVALID_TENCENT_BAR_GEOMETRY")
        if row["volume"] < 0:
            raise ValueError("INVALID_TENCENT_VOLUME")
        out.append(row)
    dates = [x["date"] for x in out]
    if dates != sorted(set(dates)):
        raise ValueError("DUPLICATE_OR_UNSORTED_TENCENT_HISTORY")
    if len(out) < 21 or dates[-1] != target:
        raise ValueError("TENCENT_TARGET_OR_HISTORY_MISSING")
    return out


def compare_independent(native, independent, target):
    right = {r["date"]: r for r in independent}
    pairs = [(left, right[left["date"]]) for left in native if left["date"] in right]
    if len(pairs) < 21:
        raise ValueError("INDEPENDENT_OVERLAP_LT_21")
    mismatches = []
    for left, other in pairs:
        for key in ("open", "high", "low", "close"):
            if abs(float(left[key]) - float(other[key])) > OHLC_TOLERANCE + 1e-9:
                mismatches.append((left["date"], key))
                break
    if mismatches:
        raise ValueError("INDEPENDENT_OHLC_DISAGREEMENT")
    latest = next((p for p in pairs if p[0]["date"] == target), None)
    if latest is None:
        raise ValueError("INDEPENDENT_TARGET_NOT_OVERLAPPED")
    lv, rv = float(latest[0]["volume"]), float(latest[1]["volume"])
    if lv == 0 or rv == 0:
        if lv != rv:
            raise ValueError("LATEST_VOLUME_ZERO_SEMANTICS_MISMATCH")
        deviation = 0.0
        status = "exact"
    else:
        deviation = abs(lv / rv - 1.0)
        if lv == rv:
            status = "exact"
        elif deviation <= LATEST_VOLUME_MAX_RELATIVE_DEVIATION:
            status = "bounded_provider_reconciliation"
        else:
            raise ValueError("LATEST_VOLUME_OUTSIDE_CALIBRATED_BOUND")
    return {
        "overlap_sessions": len(pairs),
        "ohlc_absolute_tolerance": OHLC_TOLERANCE,
        "independent_provider": "Tencent HK qfq daily",
        "volume": {
            "calibration_run_id": CALIBRATION_RUN_ID,
            "latest_session_max_relative_deviation": LATEST_VOLUME_MAX_RELATIVE_DEVIATION,
            "unit_semantics": UNIT_SEMANTICS,
            "latest_relative_deviation": deviation,
            "latest_status": status,
            "historical_volume_not_used_for_admission": True,
        },
    }


def build_preflight(code, target, universe, native_cache, independent, source):
    from src.services.market_data_integrity import validate_daily_context, daily_consistency_facts

    member = next((x for x in universe["members"] if x["code"] == code), None)
    if member is None or not member.get("channels") or not universe.get("full_union_verified"):
        raise ValueError("OFFICIAL_UNIVERSE_IDENTITY_UNVERIFIED")
    if native_cache.get("target_session") != target:
        raise ValueError("NATIVE_CACHE_TARGET_MISMATCH")
    raw = (native_cache.get("histories") or {}).get("hk" + code)
    if raw is None:
        raise ValueError("NATIVE_CACHE_MEMBER_MISSING")
    native = normalize_native(raw, target)
    reconciliation = compare_independent(native, independent, target)
    today = dict(native[-1])
    yesterday = dict(native[-2])
    for row in (today, yesterday):
        if row.get("amount") is not None:
            try:
                if not math.isfinite(float(row["amount"])):
                    row["amount"] = None
            except (TypeError, ValueError):
                row["amount"] = None
    context = {
        "date": target,
        "today": today,
        "yesterday": yesterday,
        "volume_change_ratio": round(today["volume"] / yesterday["volume"], 2) if yesterday["volume"] else None,
    }
    validate_daily_context(context, target)
    now = datetime.now(timezone.utc).isoformat()
    preflight = {
        "passed": True,
        "symbol": "HK" + code,
        "stock_name": member["official_name"],
        "prices_passed": True,
        "prepared_at": now,
        "target": target,
        "today": today,
        "yesterday": yesterday,
        "facts": daily_consistency_facts(context),
        "price_reconciliation": reconciliation,
        "overlap": reconciliation["overlap_sessions"],
        "validated_native_history": native,
        "native_history_window": {
            "first": native[0]["date"],
            "last": target,
            "count": len(native),
            "scope": "Every bar in immutable native cache is bound; independent Tencent OHLC overlap is checked; historical volume is not reinterpreted.",
            "ma60_supported": len(native) >= 60,
        },
        "component_status": {
            "prices": "passed",
            "news": "passed_limited_coverage",
        },
        "news_count": 0,
        "news_count_semantics": "ADMITTED_SOURCE_URL_COUNT_NOT_SEARCH_RESULT_COUNT",
        "news_search_performed": False,
        "allowed_news_urls": [],
        "company_news_evidence": [],
        "execution_contract": {
            "version": "O_GATE_A_EXECUTION_CONTRACT_v2",
            "realtime_quote_available": False,
            "target_session": target,
            "session_fact_anchor_required": True,
        },
        "hk_report_contract": {"required_risk_ids": []},
        "risk_review_complete": False,
        "limitation": "No issuer/news item is admitted for this pool member. This is not evidence that no negative news exists. The model must not infer exhaustive news/risk clearance.",
        "sources": {
            "universe_sha256": universe["_sha256"],
            "native_cache_sha256": native_cache["_sha256"],
            "independent_tencent": source,
        },
    }
    json.dumps(preflight, allow_nan=False, default=str)
    return preflight


def prepare(code, target, universe_path, cache_path, out):
    universe_bytes = universe_path.read_bytes()
    cache_bytes = cache_path.read_bytes()
    universe = json.loads(universe_bytes)
    cache = json.loads(cache_bytes)
    universe["_sha256"] = hashlib.sha256(universe_bytes).hexdigest()
    cache["_sha256"] = hashlib.sha256(cache_bytes).hexdigest()
    response = requests.get(
        "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get",
        params={"param": f"hk{code},day,,,180,qfq"},
        timeout=(8, 18),
    )
    response.raise_for_status()
    raw = response.content
    payload = json.loads(raw)
    independent = tencent_rows(payload, code, target)
    source = {
        "provider": "Tencent HK qfq daily",
        "url": response.url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    preflight = build_preflight(code, target, universe, cache, independent, source)
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / "preflight.json", preflight)
    atomic_json(out / "independent-source.json", source)
    return {
        "symbol": "HK" + code,
        "status": "PASS_POOL_PREFLIGHT_V1",
        "target": target,
        "overlap": preflight["overlap"],
        "model_requests": 0,
        "news_admitted": 0,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--universe", type=Path, required=True)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        print(json.dumps(prepare(args.code, args.target, args.universe, args.cache, args.out), ensure_ascii=False))
    except Exception as exc:
        import re
        reason = str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_ :.-]{2,180}", str(exc)) else type(exc).__name__
        args.out.mkdir(parents=True, exist_ok=True)
        atomic_json(args.out / "FREE_PREFLIGHT_STATUS.json", {
            "status": "FAILED",
            "reason": reason,
            "model_requests": 0,
        })
        raise
