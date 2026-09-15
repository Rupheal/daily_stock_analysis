"""Sanitized, data-only diagnosis for the Xiaomi acceptance preflight.

This tool intentionally emits no raw price/news payloads, credentials, prompts,
or model responses. It never configures or calls an LLM.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import sys

from prepare_xiaomi_acceptance import prepare, REPO_ROOT
from data_provider.tencent_fetcher import _extract_kline_rows
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
    p = ROOT / "tencent_history.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            rows = _extract_kline_rows(raw.get("result", {}), symbol="hk01810")
            dates = sorted(str(r.get("date")) for r in rows if r.get("date") and (not target or str(r.get("date")) <= target))
            out["primary_rows"] = len(dates)
            out["primary_last"] = dates[-1] if dates else None
        except Exception:
            out["primary_metadata"] = "unavailable"
    q = ROOT / "independent_history.json"
    if q.exists():
        try:
            raw = json.loads(q.read_text())
            rows = raw.get("result", [])
            dates = sorted(str(r.get("date"))[:10] for r in rows if r.get("date") and (not target or str(r.get("date"))[:10] <= target))
            out["independent_rows"] = len(dates)
            out["independent_last"] = dates[-1] if dates else None
        except Exception:
            out["independent_metadata"] = "unavailable"
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
            "schema": "dsa-xiaomi-preflight-diagnostic-v1",
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
        "schema": "dsa-xiaomi-preflight-diagnostic-v1",
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
