"""Run004 generic pool bounded DeepSeek ranking pilot.

Public-safe by construction: no prompt, raw provider response, free-form model text,
or reasoning content is persisted or printed. Every universe member remains in the
ranking denominator as either ranked or isolated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.dsa_prediction_ledger import freeze_prediction
from src.services.dsa_ranking_envelope import build_ranking_envelope, canonical_hash

API_URL = "https://api.deepseek.com/chat/completions"
MODEL_DEFAULT = "deepseek-v4-flash"
SCHEMA_VERSION = "run004-pool-safe-v3"
PEAK_INPUT_CNY_PER_M = 3.0
PEAK_OUTPUT_CNY_PER_M = 9.0
MAX_OUTPUT_TOKENS = 320
STANCES = {"positive", "neutral", "negative"}
CONFIDENCES = {"low", "medium", "high"}
REASON_CODES = {
    "trend_above_mas", "trend_below_mas", "mixed_ma_structure", "positive_momentum",
    "negative_momentum", "high_realized_volatility", "low_realized_volatility",
    "volume_expansion", "volume_contraction", "near_recent_high", "near_recent_low",
    "insufficient_edge",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def canonical_code(value):
    text = str(value).upper().removeprefix("HK").removesuffix(".HK")
    return "HK" + text.zfill(5)


def load_inputs(db_path, universe_path, integrity_path, target, expected_track):
    universe = json.loads(Path(universe_path).read_text(encoding="utf-8"))
    integrity = json.loads(Path(integrity_path).read_text(encoding="utf-8"))
    members = [canonical_code(r["code"]) for r in universe["members"]]
    if universe.get("member_count") != len(members) or len(set(members)) != len(members):
        raise ValueError("universe_denominator_mismatch")
    coverage = integrity.get("coverage") or []
    if integrity.get("track") != expected_track or integrity.get("denominator") != len(members):
        raise ValueError("integrity_denominator_mismatch")
    by_code = {canonical_code(r["code"]): r for r in coverage}
    if set(by_code) != set(members) or len(by_code) != len(coverage):
        raise ValueError("integrity_membership_mismatch")
    if integrity.get("target") != target:
        raise ValueError("integrity_target_mismatch")
    expected_db = integrity.get("database_sha256")
    actual_db = file_sha256(db_path)
    if expected_db and expected_db != actual_db:
        raise ValueError("database_hash_mismatch")
    return universe, integrity, members, by_code, actual_db


def _rows(con, code, target):
    values = con.execute(
        "SELECT date,open,high,low,close,volume,ma5,ma10,ma20,volume_ratio,data_source "
        "FROM stock_daily WHERE code=? COLLATE NOCASE AND date<=? ORDER BY date",
        (code, target),
    ).fetchall()
    if len(values) < 21 or str(values[-1][0])[:10] != target:
        raise ValueError("missing_21bar_history")
    return values


def _ret(closes, n):
    if len(closes) <= n or closes[-1-n] <= 0:
        return None
    return (closes[-1] / closes[-1-n] - 1) * 100


def technical_features(db_path, code, target):
    with sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True) as con:
        rows = _rows(con, code, target)
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows[-20:]]
    lows = [float(r[3]) for r in rows[-20:]]
    latest = rows[-1]
    close = closes[-1]
    returns = [(b/a-1)*100 for a, b in zip(closes[-21:-1], closes[-20:]) if a > 0]
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((x-mean)**2 for x in returns) / len(returns) if returns else 0.0
    vol20 = math.sqrt(variance) * math.sqrt(252)
    return {
        "code": code,
        "as_of": target,
        "close": round(close, 6),
        "return_1d_pct": round(_ret(closes, 1), 6),
        "return_5d_pct": round(_ret(closes, 5), 6),
        "return_10d_pct": round(_ret(closes, 10), 6),
        "return_20d_pct": round(_ret(closes, 20), 6),
        "ma5": round(float(latest[6]), 6) if latest[6] is not None else None,
        "ma10": round(float(latest[7]), 6) if latest[7] is not None else None,
        "ma20": round(float(latest[8]), 6) if latest[8] is not None else None,
        "bias_ma5_pct": round((close/float(latest[6])-1)*100, 6) if latest[6] else None,
        "bias_ma20_pct": round((close/float(latest[8])-1)*100, 6) if latest[8] else None,
        "volume_ratio": round(float(latest[9]), 6) if latest[9] is not None else None,
        "realized_vol20_ann_pct": round(vol20, 6),
        "position_in_20d_range": round((close-min(lows))/(max(highs)-min(lows)), 6) if max(highs)>min(lows) else None,
        "source": str(latest[10] or ""),
    }


def request_object(model, features):
    system = (
        "You are a bounded ranking component. Return JSON only. Use only the supplied technical facts. "
        "Do not predict a probability, target price, trade, position, or narrative. "
        "score is a 0-100 research-priority technical score, not a probability. "
        "Valid stance: positive, neutral, negative. Valid confidence: low, medium, high. "
        "reason_codes must contain 1-3 values from the supplied enum."
    )
    user = {
        "schema": SCHEMA_VERSION,
        "task": "score this security for cross-sectional technical research priority",
        "reason_code_enum": sorted(REASON_CODES),
        "facts": features,
        "required_json": {"score": "integer 0..100", "stance": "enum", "confidence": "enum", "reason_codes": ["enum"]},
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, sort_keys=True, separators=(",", ":"))},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }


def conservative_request_reserve_cny(body):
    body_bytes = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return body_bytes*PEAK_INPUT_CNY_PER_M/1_000_000 + MAX_OUTPUT_TOKENS*PEAK_OUTPUT_CNY_PER_M/1_000_000


def usage_peak_cost_cny(usage):
    prompt = int((usage or {}).get("prompt_tokens") or 0)
    completion = int((usage or {}).get("completion_tokens") or 0)
    return prompt*PEAK_INPUT_CNY_PER_M/1_000_000 + completion*PEAK_OUTPUT_CNY_PER_M/1_000_000


def _post_json(url, body, api_key, timeout=45):
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TRIDENT-Run004/1.0",
    })
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read(200000))
    except HTTPError as exc:
        raise RuntimeError(f"provider_http_{exc.code}") from None
    except URLError:
        raise RuntimeError("provider_network_error") from None


def validate_model_result(value):
    required = {"score", "stance", "confidence", "reason_codes"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("invalid_model_schema_missing_required")
    projected = {key: value[key] for key in required}
    score = projected["score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("invalid_score")
    if projected["stance"] not in STANCES or projected["confidence"] not in CONFIDENCES:
        raise ValueError("invalid_model_enum")
    reasons = projected["reason_codes"]
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= 3 or len(set(reasons)) != len(reasons):
        raise ValueError("invalid_reason_codes")
    if any(r not in REASON_CODES for r in reasons):
        raise ValueError("unknown_reason_code")
    return {"score": score, "stance": projected["stance"], "confidence": projected["confidence"], "reason_codes": reasons}


def parse_provider_response(data):
    try:
        content = data["choices"][0]["message"]["content"]
        model = str(data.get("model") or "")
        usage = dict(data.get("usage") or {})
        parsed = json.loads(content)
    except Exception:
        raise ValueError("provider_response_not_valid_json") from None
    return validate_model_result(parsed), model, usage


def execute(args, post_json=_post_json):
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    universe, integrity, members, coverage, db_hash = load_inputs(args.db, args.universe, args.integrity, args.target, args.track)
    integrity_hash = file_sha256(args.integrity)
    universe_hash = file_sha256(args.universe)
    config = {
        "schema": SCHEMA_VERSION, "track": args.track, "model": args.model, "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0, "thinking": "disabled", "response_format": "json_object",
        "max_requests": args.max_requests, "max_cny": args.max_cny,
        "peak_input_cny_per_m": PEAK_INPUT_CNY_PER_M, "peak_output_cny_per_m": PEAK_OUTPUT_CNY_PER_M,
        "reason_codes": sorted(REASON_CODES),
    }
    config_hash = canonical_hash(config)
    candidates, isolated = [], []
    for code in members:
        row = coverage[code]
        if row.get("status") != "passed_21_observed_daily_bars":
            isolated.append({"code": code, "reason": "b1_" + str(row.get("reason") or "isolated")})
            continue
        try:
            candidates.append((code, technical_features(args.db, code, args.target)))
        except Exception as exc:
            isolated.append({"code": code, "reason": "feature_gate:" + type(exc).__name__})
    input_projection = [{"code": c, "features": f, "feature_sha256": canonical_hash(f)} for c, f in candidates]
    input_hash = canonical_hash(input_projection)
    if len(candidates) > args.max_requests:
        for code, _ in candidates[args.max_requests:]:
            isolated.append({"code": code, "reason": "request_limit"})
        candidates = candidates[:args.max_requests]

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key and not args.dry_run:
        raise RuntimeError("missing_deepseek_api_key")
    safe_rows = []
    used_requests = 0
    estimated_peak_cost = 0.0
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    started = utcnow()
    for code, features in candidates:
        body = request_object(args.model, features)
        reserve = conservative_request_reserve_cny(body)
        if used_requests >= args.max_requests or estimated_peak_cost + reserve > args.max_cny:
            isolated.append({"code": code, "reason": "budget_guard"})
            continue
        if args.dry_run:
            result = {"score": 50, "stance": "neutral", "confidence": "low", "reason_codes": ["insufficient_edge"]}
            response_model, usage = args.model, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        else:
            used_requests += 1
            try:
                provider = post_json(API_URL, body, api_key)
                result, response_model, usage = parse_provider_response(provider)
            except Exception as exc:
                isolated.append({"code": code, "reason": "model_failure:" + str(exc)[:80]})
                estimated_peak_cost += reserve
                continue
        cost = usage_peak_cost_cny(usage)
        if not args.dry_run and cost <= 0:
            cost = reserve
        estimated_peak_cost += cost
        for key in usage_total:
            usage_total[key] += int(usage.get(key) or 0)
        safe = {
            "code": code, "score": result["score"], "stance": result["stance"],
            "confidence": result["confidence"], "reason_codes": result["reason_codes"],
            "feature_sha256": canonical_hash(features), "model": response_model or args.model,
            "usage": {k: int(usage.get(k) or 0) for k in usage_total},
            "peak_cost_estimate_cny": round(cost, 8),
        }
        safe["result_sha256"] = canonical_hash({k: safe[k] for k in ("code", "score", "stance", "confidence", "reason_codes", "feature_sha256", "model")})
        safe_rows.append(safe)
    safe_rows.sort(key=lambda r: (-r["score"], r["code"]))
    ranked = [dict(row, rank=i+1) for i, row in enumerate(safe_rows)]
    isolated.sort(key=lambda r: r["code"])
    envelope = build_ranking_envelope(members, ranked, isolated, as_of=args.target,
        claimed_scope="partial_with_isolations" if isolated else "full_pool_complete")
    ranking_hash = canonical_hash([{"code": r["code"], "rank": r["rank"], "score": r["score"], "result_sha256": r["result_sha256"]} for r in ranked])
    prediction_payload_hash = canonical_hash({"ranked": ranked, "isolated": isolated, "envelope": envelope})
    finished = utcnow()
    package = {
        "schema_version": 1, "run_id": args.run_id, "status": "SAFE_POOL_PILOT_COMPLETE",
        "generated_at": finished, "as_of": args.target, "track": args.track, "model": args.model,
        "universe_id": universe.get("universe_id"), "denominator": len(members),
        "ranked_count": len(ranked), "isolated_count": len(isolated), "model_http_requests": used_requests,
        "ranked": ranked, "isolated": isolated, "ranking_envelope": envelope,
        "hashes": {"database_sha256": db_hash, "universe_file_sha256": universe_hash,
                   "integrity_file_sha256": integrity_hash, "input_sha256": input_hash,
                   "config_sha256": config_hash, "prediction_payload_sha256": prediction_payload_hash,
                   "ranking_sha256": ranking_hash},
        "usage": usage_total,
        "cost": {"basis": "peak price guard; estimate, not invoice", "estimated_peak_cny": round(estimated_peak_cost, 8),
                 "hard_cap_cny": args.max_cny},
        "privacy": {"raw_prompt_saved": False, "raw_provider_response_saved": False,
                    "reasoning_saved": False, "free_form_model_text_saved": False},
        "started_at": started,
    }
    forbidden = ("raw_response", "prompt", "reasoning", "messages", "provider_response", "analysis", "explanation")
    serialized = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if any(f'"{key}"' in serialized for key in forbidden):
        raise RuntimeError("unsafe_serialization_key")
    ranking_path = out / "pool-safe-ranking.json"
    ranking_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    data_as_of = args.target + "T16:00:00+08:00"
    ledger_record = {
        "run_id": args.run_id, "generated_at": finished, "as_of": data_as_of,
        "universe_sha256": universe_hash, "input_sha256": input_hash,
        "model_version": args.model, "config_sha256": config_hash,
        "prediction_payload_sha256": prediction_payload_hash, "ranking_sha256": ranking_hash,
        "status": package["status"],
    }
    ledger_path = freeze_prediction(out / "prediction-ledger", ledger_record)
    manifest = {
        "run_id": args.run_id, "files": {
            "pool-safe-ranking.json": file_sha256(ranking_path),
            str(Path("prediction-ledger") / ledger_path.name): file_sha256(ledger_path),
        },
        "privacy_contract": package["privacy"], "model_http_requests": used_requests,
        "estimated_peak_cny": round(estimated_peak_cost, 8),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RUN004_POOL_SAFE", json.dumps({"run_id": args.run_id, "track": args.track, "denominator": len(members),
        "ranked": len(ranked), "isolated": len(isolated), "http_requests": used_requests,
        "estimated_peak_cny": round(estimated_peak_cost, 8), "ranking_sha256": ranking_hash}, ensure_ascii=False), flush=True)
    return package


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--integrity", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--target", default="2026-09-11")
    p.add_argument("--track", choices=("U", "O"), default="O")
    p.add_argument("--model", default=MODEL_DEFAULT)
    p.add_argument("--run-id", default="TRI-DSA-DEV-20260913-004-POOL")
    p.add_argument("--max-cny", type=float, default=5.0)
    p.add_argument("--max-requests", type=int, default=660)
    p.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
