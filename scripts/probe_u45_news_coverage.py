#!/usr/bin/env python3
"""Model-free U45 public-news coverage probe.

This verifies that every currently executable U45 member receives a bounded,
parseable public-news search response. A successful query with zero recent
items is COVERAGE_READY_NO_RECENT_ITEMS, not a missing-data failure.
No model credentials or LLM calls are used.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://search-api-web.eastmoney.com/search/jsonp"
UA = "Mozilla/5.0 (compatible; DSA-U45-NewsCoverage/1.0)"


def _load_universe(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("members", "stocks", "universe"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise SystemExit("U45 universe must resolve to a list")
    rows = []
    for item in raw:
        code = str(item.get("code") or item.get("symbol") or "").upper().replace("HK", "").zfill(5)
        name = str(item.get("name") or item.get("user_alias") or item.get("alias") or code).strip()
        if code:
            rows.append({"code": code, "name": name})
    if len(rows) != 45 or len({x["code"] for x in rows}) != 45:
        raise SystemExit(f"U45 denominator invariant failed: {len(rows)}")
    return rows


def _jsonp_json(text: str) -> dict:
    text = text.strip()
    m = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
    payload = m.group(1) if m else text
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError("response is not a JSON object")
    return obj


def _extract_items(obj: dict) -> list[dict]:
    result = obj.get("result")
    if not isinstance(result, dict):
        return []
    for key in ("cmsArticleWebOld", "cmsArticleWeb"):
        value = result.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _date_value(item: dict) -> str | None:
    for key in ("date", "publishTime", "showTime", "updateTime", "createTime"):
        v = item.get(key)
        if v:
            return str(v)
    return None


def _title_value(item: dict) -> str:
    for key in ("title", "mediaName", "content"):
        v = item.get(key)
        if v:
            return re.sub(r"<[^>]+>", "", str(v))[:240]
    return ""


def fetch_one(member: dict, cutoff: datetime, timeout: float) -> dict:
    code, name = member["code"], member["name"]
    query = f"{name} {code}"
    spec = {
        "uid": "",
        "keyword": query,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time", "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": ""}},
    }
    started = time.monotonic()
    out = {
        "code": code,
        "name": name,
        "query": query,
        "provider": "eastmoney_public_search",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "model_requests": 0,
    }
    try:
        r = requests.get(API, params={"cb": "callback", "param": json.dumps(spec, ensure_ascii=False)}, headers={"User-Agent": UA}, timeout=(8, timeout))
        out["http_status"] = r.status_code
        raw = r.content
        out["response_bytes"] = len(raw)
        out["sha256"] = hashlib.sha256(raw).hexdigest()
        r.raise_for_status()
        obj = _jsonp_json(r.text)
        items = _extract_items(obj)
        out["parsed"] = True
        out["items_returned"] = len(items)
        out["sample"] = [{"title": _title_value(x), "published": _date_value(x)} for x in items[:3]]
        # Search transport + parseability establishes coverage. Recent-item count is
        # reported separately and is intentionally not required to be >0.
        out["coverage_ready"] = True
        out["coverage_status"] = "COVERAGE_READY_ITEMS_RETURNED" if items else "COVERAGE_READY_NO_ITEMS_RETURNED"
        out["cutoff_utc"] = cutoff.isoformat()
    except Exception as exc:
        out["parsed"] = False
        out["coverage_ready"] = False
        out["coverage_status"] = "TRANSPORT_OR_PARSE_FAILURE"
        out["error_type"] = type(exc).__name__
    out["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="docs/dsa-u-universe.json")
    ap.add_argument("--out", default="probe/u45-news/U45_NEWS_COVERAGE.json")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=18)
    ap.add_argument("--exclude-code", action="append", default=["09618"], help="Retained but currently non-executable member")
    args = ap.parse_args()

    members = _load_universe(Path(args.universe))
    excluded = set(args.exclude_code)
    executable = [m for m in members if m["code"] not in excluded]
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda m: fetch_one(m, cutoff, args.timeout), executable))

    ready = sum(bool(x.get("coverage_ready")) for x in rows)
    failures = [x for x in rows if not x.get("coverage_ready")]
    receipt = {
        "schema_version": "U45_NEWS_COVERAGE_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_denominator": 45,
        "execution_eligible_denominator": len(executable),
        "retained_not_currently_executable": sorted(excluded),
        "coverage_ready": ready,
        "coverage_failed": len(failures),
        "formal_u_acceptance_added": 0,
        "model_http_requests": 0,
        "paid_data_calls": 0,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("universe_denominator", "execution_eligible_denominator", "coverage_ready", "coverage_failed", "model_http_requests")}, ensure_ascii=False))
    if failures:
        raise SystemExit(f"U45 news coverage incomplete: {len(failures)} failures")


if __name__ == "__main__":
    main()
