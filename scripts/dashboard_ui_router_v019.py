#!/usr/bin/env python3
"""Resolve the /tri dsa ui shortcut to the safest read-only Dashboard UI.

The router never mutates runtime state. It prefers the newest engineering-
accepted v0.19 UI only when its sanitized feed is aligned with the authoritative
execution checkout. Otherwise it falls back explicitly to v0.18 as
LAST_VALIDATED. It never silently labels fallback data as current.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

COMMAND = "/tri dsa ui"
V019_UI = "DSA_Dashboard_v0.19_Live_UI.html"
V018_UI = "DSA_Dashboard_v0.18_Live_UI.html"
V019_ACCEPT = "docs/runtime/DSA_DASHBOARD_V019_P2_SYNC_ACCEPTANCE.json"
V018_ACCEPT = "docs/runtime/DSA_DASHBOARD_V018_ACCEPTANCE.json"
V019_FEED = "DSA_DASHBOARD_LIVE_V019.json"
V019_BRANCH = "research/dsa-dashboard-v019-20260918"
V018_BRANCH = "fix/native-private-execution-20260914"


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_detector(root: Path):
    p = root / "scripts" / "dashboard_feed_lag_detector_v019.py"
    spec = importlib.util.spec_from_file_location("dsa_dashboard_lag", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def accepted(path: Path) -> bool:
    obj = load_json(path, {}) or {}
    return obj.get("status") in {
        "ACCEPTED_ENGINEERING",
        "ACCEPTED_ENGINEERING_P0_AUTHORITY_FRESHNESS",
    }


def github_blob(branch: str, path: str) -> str:
    return (
        "https://github.com/Rupheal/daily_stock_analysis/blob/"
        + branch
        + "/"
        + path
    )


def resolve(dashboard_root: Path, authority_root: Path):
    v019_ok = accepted(dashboard_root / V019_ACCEPT)
    v018_ok = accepted(dashboard_root / V018_ACCEPT)
    v019_ui_exists = (dashboard_root / V019_UI).exists()
    v018_ui_exists = (dashboard_root / V018_UI).exists()

    detector_status = "NOT_RUN"
    detector_reason = None
    latest_authority = None

    if v019_ok and v019_ui_exists and (dashboard_root / V019_FEED).exists():
        detector = load_detector(dashboard_root)
        if detector is None:
            detector_status = "DETECTOR_UNAVAILABLE"
            detector_reason = "v0.19 lag detector could not be loaded"
        else:
            report, code = detector.detect(dashboard_root, authority_root, V019_FEED)
            detector_status = report.get("status", "UNKNOWN")
            detector_reason = report.get("reason")
            latest_authority = report.get("latest_authority")
            if code == 0 and detector_status == "ALIGNED":
                feed = load_json(dashboard_root / V019_FEED, {}) or {}
                return {
                    "command": COMMAND,
                    "route_state": "CURRENT_AUTHORITY_ALIGNED",
                    "selected_version": "v0.19",
                    "selected_ui": V019_UI,
                    "selected_branch": V019_BRANCH,
                    "selected_url": github_blob(V019_BRANCH, V019_UI),
                    "badge": "CURRENT / READ ONLY",
                    "read_only": True,
                    "fallback": False,
                    "detector_status": detector_status,
                    "authority_run": (feed.get("authority") or {}).get("source_run_id"),
                    "authority_session": (feed.get("authority") or {}).get("evidence_session"),
                    "formal_strategy_acceptance": (feed.get("authority") or {}).get("strategy_acceptance"),
                    "warning": None,
                }, 0

    fallback_reason = detector_status
    if not v019_ok:
        fallback_reason = "V019_NOT_ENGINEERING_ACCEPTED"
    elif not v019_ui_exists:
        fallback_reason = "V019_UI_MISSING"
    elif not (dashboard_root / V019_FEED).exists():
        fallback_reason = "V019_FEED_MISSING"

    if v018_ok and v018_ui_exists:
        return {
            "command": COMMAND,
            "route_state": "LAST_VALIDATED_FALLBACK",
            "selected_version": "v0.18",
            "selected_ui": V018_UI,
            "selected_branch": V018_BRANCH,
            "selected_url": github_blob(V018_BRANCH, V018_UI),
            "badge": "LAST VALIDATED / READ ONLY",
            "read_only": True,
            "fallback": True,
            "fallback_reason": fallback_reason,
            "detector_status": detector_status,
            "detector_reason": detector_reason,
            "latest_authority": latest_authority,
            "warning": "v0.19 authority chain is not currently aligned; v0.18 is shown only as LAST VALIDATED, not current data.",
        }, 10

    return {
        "command": COMMAND,
        "route_state": "NO_SAFE_UI",
        "selected_version": None,
        "selected_ui": None,
        "selected_branch": None,
        "selected_url": None,
        "badge": "BLOCKED",
        "read_only": True,
        "fallback": False,
        "fallback_reason": fallback_reason,
        "detector_status": detector_status,
        "detector_reason": detector_reason,
        "warning": "No engineering-accepted safe Dashboard UI is available.",
    }, 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-root", default=".")
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    result, code = resolve(
        Path(args.dashboard_root).resolve(),
        Path(args.authority_root).resolve(),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
