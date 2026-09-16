#!/usr/bin/env python3
"""Model-free U45 public-news retrieval-quality probe.

For each currently executable U45 member, query company name and stock code
independently. Transport/parseability and article retrieval are separate facts.
A zero-item response is never interpreted as "no material news" unless the
provider retrieval shape has first been proven by positive canary results.
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
UA = "Mozilla/5.0 (compatible; DSA-U45-NewsCoverage/1.1)"


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


def _extract_items(obj: dict) -> tuple[list[dict], dict]:
    """Return article-like rows plus bounded response-shape diagnostics."""
    result = obj.get("result")
    diag = {
        "top_keys": sorted(str(k) for k in obj.keys())[:20],
        "result_type": type(result).__name__,
        "result_keys": sorted(str(k) for k in result.keys())[:30] if isinstance(result, dict) else [],
    }
    if not isinstance(result, dict):
        return [], diag

    candidates: list[dict] = []
    for key in ("cmsArticleWebOld", "cmsArticleWeb"):
        value = result.get(key)
        if isinstance(value, list):
            candidates.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            # Provider versions have used nested list containers; accept only
            # explicit list values, never arbitrary recursive objects.
            for nested_key in ("list", "data", "items", "rows"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    candidates.extend(x for x in nested if isinstance(x, dict))
                    diag.setdefault("nested_paths", []).append(f"{key}.{nested_key}")
    return candidates, diag


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


def _query_once(query: str, timeout: float) -> dict:
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
    out = {"query": query, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        r = requests.get(API, params={"cb": "callback", "param": json.dumps(spec, ensure_ascii=False)}, headers={"User-Agent": UA}, timeout=(8, timeout))
        raw = r.content
        out.update(http_status=r.status_code, response_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        r.raise_for_status()
        obj = _jsonp_json(r.text)
        items, diag = _extract_items(obj)
        out.update(parsed=True, items_returned=len(items), response_shape=diag,
                   sample=[{"title": _title_value(x), "published": _date_value(x)} for x in items[:3]])
    except Exception as exc:
        out.update(parsed=False, items_returned=0, error_type=type(exc).__name__)
    out["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return out


def fetch_one(member: dict, cutoff: datetime, timeout: float) -> dict:
    code, name = member["code"], member["name"]
    name_result = _query_once(name, timeout)
    code_result = _query_once(code, timeout)
    attempts = [name_result, code_result]
    transport_ready = all(x.get("parsed") for x in attempts)
    total_items = sum(int(x.get("items_returned") or 0) for x in attempts)
    return {
        "code": code,
        "name": name,
        "provider": "eastmoney_public_search",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "transport_parse_ready": transport_ready,
        "items_returned_across_queries": total_items,
        "retrieval_positive": total_items > 0,
        "retrieval_status": "ITEMS_RETURNED" if total_items > 0 else ("ZERO_ITEMS_RETRIEVAL_UNPROVEN" if transport_ready else "TRANSPORT_OR_PARSE_FAILURE"),
        "attempts": attempts,
        "model_requests": 0,
    }


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

    transport_ready = sum(bool(x.get("transport_parse_ready")) for x in rows)
    positives = sum(bool(x.get("retrieval_positive")) for x in rows)
    transport_failures = [x for x in rows if not x.get("transport_parse_ready")]
    # A positive canary proves that the provider path can actually return article
    # rows today. Without one, all zero results remain retrieval-unproven.
    retrieval_quality_proven = positives > 0
    receipt = {
        "schema_version": "U45_NEWS_COVERAGE_v1_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_denominator": 45,
        "execution_eligible_denominator": len(executable),
        "retained_not_currently_executable": sorted(excluded),
        "transport_parse_ready": transport_ready,
        "transport_parse_failed": len(transport_failures),
        "members_with_items": positives,
        "members_with_zero_items": len(rows) - positives,
        "retrieval_quality_proven": retrieval_quality_proven,
        "news_semantic_ready": 0,
        "formal_u_acceptance_added": 0,
        "model_http_requests": 0,
        "paid_data_calls": 0,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("universe_denominator", "execution_eligible_denominator", "transport_parse_ready", "transport_parse_failed", "members_with_items", "retrieval_quality_proven", "model_http_requests")}, ensure_ascii=False))
    if transport_failures:
        raise SystemExit(f"U45 news transport incomplete: {len(transport_failures)} failures")
    if not retrieval_quality_proven:
        raise SystemExit("NEWS_RETRIEVAL_QUALITY_UNPROVEN_ALL_QUERIES_ZERO")


if __name__ == "__main__":
    main()
