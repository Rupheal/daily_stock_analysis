"""Sanitized, data-only diagnosis for the Xiaomi acceptance preflight.

This tool intentionally emits no raw price/news payloads, credentials, prompts,
or model responses. It never configures or calls an LLM.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import re

import pandas as pd

from prepare_xiaomi_acceptance import prepare, REPO_ROOT
from data_provider.tencent_fetcher import TencentFetcher, _extract_kline_rows
from src.core.trading_calendar import get_effective_trading_date

ROOT = REPO_ROOT / "probe-diagnostic"


def _tasks():
    p = ROOT / "acceptance-queue.json"
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text())
        tasks = value.get("tasks", {})
        return tasks if isinstance(tasks, dict) else {}
    except Exception:
        return {}


def _stage(tasks):
    for name in ("prices", "news", "issuer", "manifest"):
        if tasks.get(name, "pending") == "pending":
            return name
    return "post_manifest"


def _classify(stage, exc):
    msg = str(exc)
    known = [
        ("Yahoo independent history unavailable", "PRICE_YAHOO_EMPTY"),
        ("Incomplete latest session/history coverage", "PRICE_LATEST_OR_HISTORY_INCOMPLETE"),
        ("Insufficient independent overlap", "PRICE_OVERLAP_LT60"),
        ("Issuer feed delegation no longer verifiable", "ISSUER_DELEGATION_UNVERIFIED"),
        ("Issuer announcement listing missing", "ISSUER_LISTING_MISSING"),
        ("Future issuer disclosure date", "ISSUER_FUTURE_DATE"),
        ("Recent issuer announcement has no original attachment", "ISSUER_ATTACHMENT_MISSING"),
        ("No recent issuer announcement listing to inspect", "ISSUER_RECENT_LISTING_EMPTY"),
        ("Reviewed news violates regional source policy", "NEWS_SOURCE_POLICY"),
        ("Insufficient dated company evidence", "NEWS_EVIDENCE_INSUFFICIENT"),
    ]
    for needle, code in known:
        if needle in msg:
            return code
    m = re.search(r"Missing independent values: ([A-Za-z_]+)", msg)
    if m:
        return "PRICE_NONFINITE_" + m.group(1).upper()
    m = re.search(r"Independent source disagreement: ([A-Za-z_]+)", msg)
    if m:
        return "PRICE_DISAGREEMENT_" + m.group(1).upper()
    return stage.upper() + "_EXCEPTION_" + type(exc).__name__.upper()


def _price_metadata():
    out = {}
    try:
        target = str(get_effective_trading_date("hk"))
        out["target"] = target
    except Exception:
        target = None
    primary, independent = None, None
    p = ROOT / "tencent_history.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            rows = _extract_kline_rows(raw.get("result", {}), symbol="hk01810")
            fetcher = TencentFetcher()
            frame = pd.DataFrame(rows)
            primary = fetcher._normalize_data(frame, "HK01810")
            primary["date"] = pd.to_datetime(primary["date"]).dt.strftime("%Y-%m-%d")
            if target:
                primary = primary[primary["date"] <= target]
            primary = primary.sort_values("date")
            out["primary_rows"] = len(primary)
            out["primary_last"] = primary.iloc[-1]["date"] if len(primary) else None
            out["primary_volume_semantics"] = "Tencent HK kline row[5], repository parser treats as shares"
            out["primary_adjustment"] = "qfq"
        except Exception:
            out["primary_metadata"] = "unavailable"
    q = ROOT / "independent_history.json"
    if q.exists():
        try:
            raw = json.loads(q.read_text())
            independent = pd.DataFrame(raw.get("result", []))
            if not independent.empty:
                independent["date"] = pd.to_datetime(independent["date"]).dt.strftime("%Y-%m-%d")
                if target:
                    independent = independent[independent["date"] <= target]
                independent = independent.sort_values("date")
            out["independent_rows"] = len(independent)
            out["independent_last"] = independent.iloc[-1]["date"] if len(independent) else None
            out["independent_volume_semantics"] = "Yahoo history Volume field"
            out["independent_adjustment"] = "auto_adjust=True"
        except Exception:
            out["independent_metadata"] = "unavailable"
    if primary is not None and independent is not None and not primary.empty and not independent.empty:
        try:
            keep = [c for c in ("date", "open", "high", "low", "close", "volume") if c in independent.columns]
            overlap = primary[["date", "open", "high", "low", "close", "volume"]].merge(
                independent[keep], on="date", suffixes=("_tencent", "_yahoo"), validate="one_to_one")
            out["overlap_rows"] = len(overlap)
            if len(overlap):
                for field in ("open", "high", "low", "close"):
                    left = pd.to_numeric(overlap[field + "_tencent"], errors="coerce")
                    right = pd.to_numeric(overlap[field + "_yahoo"], errors="coerce")
                    out[field + "_max_abs_diff"] = round(float((left - right).abs().max()), 6)
                tv = pd.to_numeric(overlap["volume_tencent"], errors="coerce")
                yv = pd.to_numeric(overlap["volume_yahoo"], errors="coerce")
                valid = tv.notna() & yv.notna() & (yv != 0)
                ratios = (tv[valid] / yv[valid]).astype(float)
                out["volume_valid_rows"] = int(valid.sum())
                out["volume_exact_match_rows"] = int(((tv[valid] - yv[valid]).abs() == 0).sum())
                out["volume_mismatch_rows"] = int(valid.sum() - ((tv[valid] - yv[valid]).abs() == 0).sum())
                if len(ratios):
                    out["volume_ratio_median_tencent_over_yahoo"] = round(float(ratios.median()), 6)
                    out["volume_ratio_min"] = round(float(ratios.min()), 6)
                    out["volume_ratio_max"] = round(float(ratios.max()), 6)
                    out["volume_ratio_latest"] = round(float(ratios.iloc[-1]), 6)
                    out["volume_ratio_near_1_rows"] = int(((ratios - 1).abs() <= 0.000001).sum())
                    out["volume_ratio_near_100_rows"] = int(((ratios - 100).abs() <= 0.0001).sum())
                    out["volume_ratio_near_0_01_rows"] = int(((ratios - 0.01).abs() <= 0.000001).sum())
                split_col = next((c for c in independent.columns if str(c).lower() == "stock splits"), None)
                if split_col:
                    split_map = independent[["date", split_col]].copy()
                    split_map[split_col] = pd.to_numeric(split_map[split_col], errors="coerce").fillna(0)
                    out["independent_nonzero_split_rows"] = int((split_map[split_col] != 0).sum())
        except Exception:
            out["overlap_metadata"] = "unavailable"
    return out


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = prepare(root=ROOT)
    except Exception as exc:
        tasks = _tasks()
        stage = _stage(tasks)
        report = {
            "schema": "dsa-xiaomi-preflight-diagnostic-v2",
            "passed": False,
            "stage": stage,
            "code": _classify(stage, exc),
            "exception_type": type(exc).__name__,
            "tasks": tasks,
            "price_metadata": _price_metadata(),
            "model_http_requests": 0,
            "raw_stdout_disclosed": False,
            "raw_stderr_disclosed": False,
            "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    report = {
        "schema": "dsa-xiaomi-preflight-diagnostic-v2",
        "passed": bool(result.get("passed")),
        "stage": "complete",
        "code": "PREFLIGHT_PASS",
        "tasks": _tasks(),
        "price_metadata": _price_metadata(),
        "news_count": result.get("news_count"),
        "origin_count": len(result.get("origins", [])),
        "overlap": result.get("overlap"),
        "model_http_requests": 0,
        "raw_stdout_disclosed": False,
        "raw_stderr_disclosed": False,
        "diagnosed_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
