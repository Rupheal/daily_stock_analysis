"""Run006 B1 recovery: diagnose Yahoo geometry isolates without changing any frozen input.

Reads the frozen O-integrity report and retained O660 DB, then refetches only the 114
exact failing Yahoo dates with yfinance in both unadjusted and auto-adjusted modes.
The output is diagnostic evidence only; it never repairs a bar and makes no model call.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Lock

import yfinance as yf

FIELDS = ("open", "high", "low", "close", "volume")
EXPECTED_DB_SHA = "f1b50fa459e229455fddadb6fbd23823199ec5ea4927d289f54ad683ed9a045b"
EXPECTED_COUNTS = {
    "independent_daily_disagreement": 132,
    "ValueError:invalid_daily_geometry": 114,
    "ValueError:missing_latest_session_or_21_bar_history": 7,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yf_symbol(code: str) -> str:
    base = code.upper().removeprefix("HK").lstrip("0") or "0"
    return base.zfill(4) + ".HK"


def geometry(row: dict | None) -> bool | None:
    if not row:
        return None
    try:
        o, h, l, c, v = [float(row[k]) for k in FIELDS]
    except Exception:
        return None
    return 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0


def frame_row(frame, target: str) -> dict | None:
    if frame is None or frame.empty:
        return None
    for idx, r in frame.iterrows():
        if str(idx)[:10] == target:
            out = {}
            for k in ("Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits", "Capital Gains"):
                if k in frame.columns:
                    try:
                        out[k.lower().replace(" ", "_")] = float(r[k])
                    except Exception:
                        out[k.lower().replace(" ", "_")] = None
            return {
                "open": out.get("open"), "high": out.get("high"), "low": out.get("low"),
                "close": out.get("close"), "volume": out.get("volume"),
                "dividends": out.get("dividends"), "stock_splits": out.get("stock_splits"),
                "capital_gains": out.get("capital_gains"),
            }
    return None


def stored_row(db: Path, code: str, target: str) -> dict | None:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT date,open,high,low,close,volume,data_source FROM stock_daily WHERE code=? COLLATE NOCASE AND substr(date,1,10)=?",
            (code, target),
        ).fetchone()
    return dict(row) if row else None


def max_price_delta(a: dict | None, b: dict | None) -> float | None:
    if not a or not b:
        return None
    vals = []
    for k in ("open", "high", "low", "close"):
        try:
            vals.append(abs(float(a[k]) - float(b[k])))
        except Exception:
            return None
    return max(vals)


def diagnose(db: Path, item: dict) -> dict:
    code = item["code"]
    failing = item["invalid_bar"]
    target = failing["date"]
    symbol = yf_symbol(code)
    d = date.fromisoformat(target)
    start, end = str(d - timedelta(days=7)), str(d + timedelta(days=8))
    rec = {
        "code": code, "symbol": symbol, "failing_date": target,
        "frozen_invalid_bar": failing, "status": "DIAGNOSTIC_ERROR",
    }
    try:
        ticker = yf.Ticker(symbol)
        raw = ticker.history(start=start, end=end, auto_adjust=False, actions=True, repair=False)
        adj = ticker.history(start=start, end=end, auto_adjust=True, actions=True, repair=False)
        raw_bar, adj_bar = frame_row(raw, target), frame_row(adj, target)
        stored = stored_row(db, code, target)
        raw_valid, adj_valid = geometry(raw_bar), geometry(adj_bar)
        stored_valid = geometry(stored)
        if raw_bar is None or adj_bar is None:
            cls = "REFETCH_DATE_MISSING"
        elif raw_valid and not adj_valid:
            cls = "AUTO_ADJUST_INTRODUCED_GEOMETRY_ERROR"
        elif not raw_valid and not adj_valid:
            cls = "UPSTREAM_YAHOO_BAR_GEOMETRY_INVALID"
        elif raw_valid and adj_valid and stored_valid is False:
            cls = "STORED_VERSION_OR_INGESTION_DRIFT"
        elif raw_valid and adj_valid:
            cls = "CURRENT_YAHOO_BOTH_VALID"
        else:
            cls = "OTHER_GEOMETRY_STATE"
        rec.update({
            "status": "OK", "classification": cls,
            "stored_bar": stored, "raw_bar": raw_bar, "adjusted_bar": adj_bar,
            "stored_geometry_valid": stored_valid, "raw_geometry_valid": raw_valid,
            "adjusted_geometry_valid": adj_valid,
            "stored_vs_current_adjusted_max_abs_price_delta": max_price_delta(stored, adj_bar),
            "raw_vs_adjusted_max_abs_price_delta": max_price_delta(raw_bar, adj_bar),
        })
    except Exception as exc:
        rec["error"] = type(exc).__name__ + ":" + str(exc)[:180]
    return rec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--integrity", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    if sha256(args.db) != EXPECTED_DB_SHA:
        raise SystemExit("retained O660 DB hash mismatch")
    report = json.loads(args.integrity.read_text())
    if report.get("denominator") != 660 or report.get("isolated") != 253:
        raise SystemExit("frozen integrity denominator mismatch")
    if report.get("reasons") != EXPECTED_COUNTS:
        raise SystemExit("frozen isolate taxonomy mismatch")
    items = [r for r in report["coverage"] if r.get("reason") == "ValueError:invalid_daily_geometry"]
    if len(items) != 114 or any("invalid_bar" not in r for r in items):
        raise SystemExit("geometry denominator mismatch")

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(diagnose, args.db, item) for item in items]
        for f in as_completed(futures):
            rows.append(f.result())
    rows.sort(key=lambda r: r["code"])
    counts = {}
    for r in rows:
        key = r.get("classification") if r.get("status") == "OK" else "DIAGNOSTIC_ERROR"
        counts[key] = counts.get(key, 0) + 1
    if len(rows) != 114:
        raise SystemExit("diagnostic denominator lost")
    out = {
        "schema_version": 1,
        "run_id": "TRI-DSA-DAT-20260914-006-R1-GEOMETRY-PROBE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_http_requests": 0,
        "paid_data_used": False,
        "original_recovery_denominator": 253,
        "track_denominator": 114,
        "source_integrity_sha256": sha256(args.integrity),
        "source_db_sha256": sha256(args.db),
        "classification_counts": counts,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print("RUN006_GEOMETRY_PROBE", json.dumps({"denominator":114,"classification_counts":counts}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
