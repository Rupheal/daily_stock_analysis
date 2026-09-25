#!/usr/bin/env python3
"""Resolve exactly one same-session active Gate-D runtime receipt.

Fail closed on ambiguity. This helper is deterministic and read-only.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT:" + str(path))
    return value


def _offset_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(label + "_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(label + "_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(label + "_TIMEZONE_REQUIRED")
    return parsed


def resolve_runtime_receipt(receipt_dir: Path, session: str, sealed_at: str) -> dict:
    sealed = _offset_time(sealed_at, "SEALED_AT")
    matches = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            row = _read_json(path)
        except Exception:
            continue
        if row.get("session") != session:
            continue
        if row.get("shadow_simulation_only") is not True:
            continue
        if int(row.get("real_orders", 0) or 0) != 0:
            continue
        try:
            finished = _offset_time(row.get("finished_at"), "FINISHED_AT")
        except ValueError:
            continue
        if finished <= sealed:
            continue
        matches.append({
            "path": str(path),
            "finished_at": row["finished_at"],
            "run_id": row.get("run_id"),
            "authority_commit": row.get("authority_commit"),
        })

    if not matches:
        return {
            "status": "WAIT_RUNTIME_RECEIPT",
            "session": session,
            "match_count": 0,
            "selected": None,
        }
    if len(matches) != 1:
        return {
            "status": "BLOCKED_AMBIGUOUS_RUNTIME_RECEIPTS",
            "session": session,
            "match_count": len(matches),
            "selected": None,
            "matches": matches,
        }
    return {
        "status": "PASS_UNIQUE_RUNTIME_RECEIPT",
        "session": session,
        "match_count": 1,
        "selected": matches[0],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt-dir", type=Path, required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--sealed-at", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = resolve_runtime_receipt(args.receipt_dir, args.session, args.sealed_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
