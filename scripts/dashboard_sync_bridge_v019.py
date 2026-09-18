#!/usr/bin/env python3
"""Event-driven sanitized DSA Dashboard v0.19 sync bridge.

Reads the authoritative execution checkout and updates only the dashboard's
sanitized canonical feed/history. No network/model/provider calls and no secrets.
Designed for GitHub Actions or a local two-checkout validation.

Exit code 0 means either UPDATED_ALIGNED or NOOP_ALREADY_ALIGNED.
Any authority/feed mismatch fails closed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load module: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sync(
    dashboard_root: Path,
    authority_root: Path,
    authority_commit: str,
    feed_name: str = "DSA_DASHBOARD_LIVE_V019.json",
    history_name: str = "DSA_DASHBOARD_HISTORY_V019.json",
    generated_at: str | None = None,
):
    generator = load_module(
        dashboard_root / "scripts" / "dashboard_feed_generator_v019.py",
        "dashboard_feed_generator_v019",
    )
    detector = load_module(
        dashboard_root / "scripts" / "dashboard_feed_lag_detector_v019.py",
        "dashboard_feed_lag_detector_v019",
    )

    latest = detector.newest_receipt(authority_root)
    if latest is None:
        raise SystemExit("AUTHORITY_UNAVAILABLE: no compatible runtime receipt")
    latest_path, latest_receipt = latest
    latest_rel = detector.normalize_rel(latest_path, authority_root)
    latest_sha = detector.sha256_file(latest_path)

    feed_path = dashboard_root / feed_name
    history_path = dashboard_root / history_name
    current = load_json(feed_path, {}) or {}
    current_auth = current.get("authority") or {}

    same_authority = (
        current_auth.get("source_receipt") == latest_rel
        and current_auth.get("source_receipt_sha256") == latest_sha
        and current_auth.get("source_run_id") == latest_receipt.get("run_id")
        and current_auth.get("evidence_session") == str(latest_receipt.get("target_session"))
        and current_auth.get("sync_mode") == "EVENT_DRIVEN_SANITIZED_BRIDGE"
    )

    if same_authority:
        report, code = detector.detect(dashboard_root, authority_root, feed_name)
        if code != 0:
            raise SystemExit(
                "SOURCE_MISMATCH: claimed latest authority but feed metrics/hash disagree: "
                + json.dumps(report, ensure_ascii=False)
            )
        return {
            "status": "NOOP_ALREADY_ALIGNED",
            "changed": False,
            "authority_receipt": latest_rel,
            "authority_receipt_sha256": latest_sha,
            "authority_run_id": latest_receipt.get("run_id"),
            "authority_session": latest_receipt.get("target_session"),
            "authority_commit": authority_commit,
            "detector_status": report["status"],
        }

    feed = generator.build_feed(
        authority_root,
        authority_commit,
        generated_at=generated_at,
    )
    feed["meta"]["branch"] = "research/dsa-dashboard-v019-20260918"
    feed["authority"]["authority_branch"] = "fix/native-private-execution-20260914"
    feed["authority"]["authority_commit"] = authority_commit
    feed["authority"]["sync_mode"] = "EVENT_DRIVEN_SANITIZED_BRIDGE"

    tmp_feed = dashboard_root / (feed_name + ".tmp")
    tmp_feed.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_feed.replace(feed_path)

    generator.append_history(history_path, feed)

    report, code = detector.detect(dashboard_root, authority_root, feed_name)
    if code != 0:
        raise SystemExit(
            "POST_SYNC_NOT_ALIGNED: " + json.dumps(report, ensure_ascii=False)
        )

    return {
        "status": "UPDATED_ALIGNED",
        "changed": True,
        "authority_receipt": latest_rel,
        "authority_receipt_sha256": latest_sha,
        "authority_run_id": latest_receipt.get("run_id"),
        "authority_session": latest_receipt.get("target_session"),
        "authority_commit": authority_commit,
        "detector_status": report["status"],
        "updated_files": [feed_name, history_name],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-root", default=".")
    ap.add_argument("--authority-root", required=True)
    ap.add_argument("--authority-commit", required=True)
    ap.add_argument("--feed", default="DSA_DASHBOARD_LIVE_V019.json")
    ap.add_argument("--history", default="DSA_DASHBOARD_HISTORY_V019.json")
    ap.add_argument("--generated-at")
    ap.add_argument("--out")
    args = ap.parse_args()

    report = sync(
        Path(args.dashboard_root).resolve(),
        Path(args.authority_root).resolve(),
        args.authority_commit,
        args.feed,
        args.history,
        args.generated_at,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
