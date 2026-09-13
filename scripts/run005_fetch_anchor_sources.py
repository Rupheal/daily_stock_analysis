"""Fetch only predecision official sources for one Run005 historical anchor.

No post-decision/outcome page is ever requested here. The script fetches the frozen
SSE notice and walks backward from the day before the decision until it has the
21 most recent valid HKEX Main Board Daily Quotations pages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HKEX_TEMPLATE = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{yymmdd}e.htm"
USER_AGENT = "TRIDENT-Run005-PIT-Fetch/1.0"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 45) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def load_anchor(path: Path, anchor_id: str):
    root = json.loads(path.read_text(encoding="utf-8"))
    anchors = {a["anchor_id"]: a for a in root["anchors"]}
    if anchor_id not in anchors:
        raise ValueError("unknown_anchor_id")
    anchor = anchors[anchor_id]
    if len(anchor["expected_additions"]) != anchor["expected_additions_count"]:
        raise ValueError("frozen_anchor_denominator_mismatch")
    if len(set(anchor["expected_additions"])) != len(anchor["expected_additions"]):
        raise ValueError("duplicate_frozen_anchor_member")
    return root, anchor


def execute(args):
    anchors_path = Path(args.anchors)
    root, anchor = load_anchor(anchors_path, args.anchor_id)
    out = Path(args.output)
    raw = out / "raw"
    quotes = raw / "hkex"
    raw.mkdir(parents=True, exist_ok=False)
    quotes.mkdir()

    notice = fetch(anchor["source_url"], args.timeout)
    notice_path = raw / "sse-notice.html"
    notice_path.write_bytes(notice)

    decision = datetime.fromisoformat(anchor["decision_at"]).date()
    sessions_desc = []
    skipped = []
    cursor = decision - timedelta(days=1)
    attempts = 0
    while len(sessions_desc) < root["history_requirement"] and attempts < args.max_calendar_lookback:
        attempts += 1
        yymmdd = cursor.strftime("%y%m%d")
        url = HKEX_TEMPLATE.format(yymmdd=yymmdd)
        try:
            content = fetch(url, args.timeout)
            # Official valid Daily Quotations pages contain this stable header marker.
            if b"PRV.CLO./" not in content or len(content) < 100_000:
                skipped.append({"date": cursor.isoformat(), "reason": "not_valid_daily_quotations_page"})
            else:
                p = quotes / f"d{yymmdd}e.htm"
                p.write_bytes(content)
                sessions_desc.append({
                    "date": cursor.isoformat(),
                    "url": url,
                    "file": p.name,
                    "sha256": sha_bytes(content),
                    "bytes": len(content),
                })
        except HTTPError as exc:
            skipped.append({"date": cursor.isoformat(), "reason": f"http_{exc.code}"})
        except (URLError, TimeoutError):
            skipped.append({"date": cursor.isoformat(), "reason": "network_error"})
        cursor -= timedelta(days=1)

    if len(sessions_desc) != root["history_requirement"]:
        raise RuntimeError(f"could_not_resolve_{root['history_requirement']}_predecision_sessions:{len(sessions_desc)}")

    sessions = list(reversed(sessions_desc))
    if sessions[-1]["date"] >= decision.isoformat():
        raise ValueError("future_or_decision_day_quote_leak")
    fetch_receipt = {
        "schema_version": 1,
        "run_id": root["run_id"],
        "anchor_id": anchor["anchor_id"],
        "decision_at": anchor["decision_at"],
        "notice_url": anchor["source_url"],
        "notice_sha256": sha_bytes(notice),
        "notice_bytes": len(notice),
        "history_requirement": root["history_requirement"],
        "selected_sessions": sessions,
        "selected_session_count": len(sessions),
        "skipped_calendar_dates": skipped,
        "outcome_data_fetched": False,
        "paid_resources": False,
    }
    (out / "source-fetch-receipt.json").write_text(json.dumps(fetch_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "sessions.txt").write_text("\n".join(s["date"] for s in sessions) + "\n", encoding="utf-8")
    print("RUN005_ANCHOR_SOURCES_OK", json.dumps({
        "anchor_id": anchor["anchor_id"],
        "sessions": len(sessions),
        "first": sessions[0]["date"],
        "last": sessions[-1]["date"],
        "notice_sha256": fetch_receipt["notice_sha256"],
    }))
    return fetch_receipt


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--anchors", required=True)
    p.add_argument("--anchor-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--max-calendar-lookback", type=int, default=50)
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
