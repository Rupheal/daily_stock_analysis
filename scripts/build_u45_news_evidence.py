#!/usr/bin/env python3
"""Build a model-free U45 public-news evidence ledger.

A stock can pass source-coverage verification even when no qualifying article was
published in the lookback window. Recent-news absence is not evidence failure.
Formal U acceptance is never granted here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_config
from src.services.hk_company_news import approved_news_origin, refresh_company_news
from src.services.intelligence_service import IntelligenceService


def _load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256_json(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--min-successful-channels", type=int, default=2)
    args = ap.parse_args()
    if not 1 <= args.days <= 7:
        raise SystemExit("--days must be 1..7")
    if not 1 <= args.min_successful_channels <= 7:
        raise SystemExit("--min-successful-channels must be 1..7")

    universe = _load(args.universe)
    members = universe.get("members", [])
    if universe.get("member_count") != 45 or len(members) != 45:
        raise SystemExit("U45 denominator must remain exactly 45")

    config = get_config()
    service = IntelligenceService(config=config)
    rows = []
    for m in members:
        code = str(m["code"]).zfill(5)
        name = m.get("user_alias") or m.get("official_name") or code
        try:
            result = refresh_company_news(service, "hk" + code, name, days=args.days)
            diagnostics = result.get("diagnostics") or []
            successful = [d for d in diagnostics if not d.get("error")]
            failed = [d for d in diagnostics if d.get("error")]
            items = result.get("items") or []
            invalid_origins = [x for x in items if not approved_news_origin(x)]
            successful_channels = len({str(d.get("source")) for d in successful if d.get("source")})
            sources_checked = sorted({str(d.get("source")) for d in diagnostics if d.get("source")})
            publisher_families = sorted({approved_news_origin(x)[0] for x in items if approved_news_origin(x)})
            item_times = [str(x.get("published_at")) for x in items if x.get("published_at")]
            coverage_ready = successful_channels >= args.min_successful_channels and not invalid_origins
            status = "NEWS_COVERAGE_READY" if coverage_ready else "NEWS_COVERAGE_BLOCKED"
            reason = None if coverage_ready else "insufficient_successful_public_channels_or_origin_policy_failure"
            rows.append({
                "code": code,
                "name": name,
                "status": status,
                "news_ready": coverage_ready,
                "lookback_days": args.days,
                "successful_channels": successful_channels,
                "sources_checked": sources_checked,
                "failed_channels": sorted({str(d.get("source")) for d in failed if d.get("source")}),
                "accepted_items": len(items),
                "publisher_families": publisher_families,
                "no_recent_approved_news": coverage_ready and len(items) == 0,
                "published_time_min": min(item_times) if item_times else None,
                "published_time_max": max(item_times) if item_times else None,
                "diagnostics_sha256": _sha256_json(diagnostics),
                "items_sha256": _sha256_json(items),
                "missing_reason": reason,
                "formal_accepted": False,
            })
        except Exception as exc:
            rows.append({
                "code": code,
                "name": name,
                "status": "NEWS_COVERAGE_BLOCKED",
                "news_ready": False,
                "lookback_days": args.days,
                "successful_channels": 0,
                "sources_checked": [],
                "failed_channels": [],
                "accepted_items": 0,
                "publisher_families": [],
                "no_recent_approved_news": False,
                "published_time_min": None,
                "published_time_max": None,
                "diagnostics_sha256": None,
                "items_sha256": None,
                "missing_reason": "refresh_exception:" + type(exc).__name__,
                "formal_accepted": False,
            })

    ready = sum(bool(x["news_ready"]) for x in rows)
    out = {
        "schema_version": "U45_NEWS_EVIDENCE_v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "universe_id": universe.get("universe_id"),
        "denominator": 45,
        "lookback_days": args.days,
        "minimum_successful_public_channels": args.min_successful_channels,
        "coverage_ready": ready,
        "coverage_blocked": 45 - ready,
        "formal_accepted": 0,
        "absence_is_not_failure": True,
        "model_calls": 0,
        "paid_data_calls": 0,
        "members": rows,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "Universe": "45/45",
        "News Coverage Ready": f"{ready}/45",
        "News Coverage Blocked": f"{45-ready}/45",
        "Formal Accepted": "0/45",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
