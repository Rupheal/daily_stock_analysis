"""Run an unchanged native CLI in an isolated checkout; audit every requested code.

This is data acquisition evidence, never full analysis or independent price verification.
The O smoke scope cannot stand in for the still-unresolved official union N.
For the explicitly authorized Run018 recovery, ``--target-boundary-adapter``
changes only Yahoo retrieval boundary/materialization outside the frozen checkout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from math import isfinite


def export_market_history(database, codes, target, destination):
    """Allowlist market bars for reuse; never export model/identity/account tables."""
    allowed=('date','open','high','low','close','volume','amount','pct_chg','ma5','ma10','ma20','volume_ratio','data_source')
    histories={code:[] for code in codes}
    if database.exists():
        con=sqlite3.connect(f'file:{database}?mode=ro',uri=True)
        try:
            columns={row[1] for row in con.execute('PRAGMA table_info(stock_daily)')}
            selected=[k for k in allowed if k in columns]
            if not {'date','open','high','low','close','volume'}<=set(selected):raise ValueError('MARKET_HISTORY_SCHEMA_MISSING')
            for code in codes:
                for raw in con.execute('SELECT '+','.join(selected)+' FROM stock_daily WHERE code=? COLLATE NOCASE AND substr(date,1,10)<=? ORDER BY date',(code,target)):
                    histories[code].append({k:(None if isinstance(v,float) and not isfinite(v) else v) for k,v in zip(selected,raw)})
        finally:con.close()
    result={'schema':'DSA_PUBLIC_MARKET_HISTORY_v1','target_session':target,'requested_denominator':len(codes),'histories':histories,'model_content_included':False,'independent_validation':False}
    destination.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def audit_database(database, codes, expected_date):
    records = []
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True) if database.exists() else None
    try:
        for code in codes:
            record = {"code": code, "status": "missing", "bars": 0}
            try:
                rows = connection.execute(
                    "SELECT date, open, high, low, close, volume, code FROM stock_daily WHERE code=? COLLATE NOCASE ORDER BY date",
                    (code,),
                ).fetchall() if connection else []
                record["bars"] = len(rows)
                if rows:
                    if len({row[6] for row in rows}) != 1:
                        raise ValueError("Ambiguous case aliases in native database")
                    last = rows[-1]
                    record.update(database_code=last[6], latest_date=str(last[0])[:10], latest_ohlcv=list(last[1:6]))
                    valid = all(v is not None and isfinite(float(v)) for v in last[1:6])
                    valid = valid and 0 < last[3] <= min(last[1], last[4]) <= max(last[1], last[4]) <= last[2] and last[5] >= 0
                    record["status"] = "current_valid_bar" if valid and record["latest_date"] == expected_date else "invalid_or_stale"
            except Exception as exc:
                record.update(status="audit_failed", error=type(exc).__name__ + ": " + str(exc))
            records.append(record)
    finally:
        if connection:
            connection.close()
    return records


def build_native_command(checkout, codes, expected_date, target_boundary_adapter=False):
    native_args = ["--stocks", ",".join(codes), "--dry-run", "--no-notify",
                   "--no-market-review", "--force-run", "--workers", "3"]
    if not target_boundary_adapter:
        return [sys.executable, "main.py"] + native_args
    wrapper = Path(__file__).resolve().parent / "run_original_with_target_adapter.py"
    return [sys.executable, str(wrapper), "--checkout", str(checkout), "--target", expected_date, "--"] + native_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--scope", choices=["U45_data_only", "O_single_stock_smoke", "O_full_pool_data_only", "O_r0_membership_data_only"], required=True)
    parser.add_argument("--expected-date", required=True)
    parser.add_argument("--decision-session", help="Official pool session; completed price session may precede it")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--target-boundary-adapter", action="store_true")
    args = parser.parse_args()
    checkout, output = args.checkout.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw_universe = args.universe.read_bytes()
    universe = json.loads(raw_universe)
    all_codes = ["hk" + c["code"] for c in universe["members"]]
    if len(set(all_codes)) != universe["member_count"] or len(all_codes) != universe["member_count"]:
        raise ValueError("Frozen universe count or uniqueness mismatch")
    if args.scope == "O_full_pool_data_only":
        if not universe.get("full_union_verified") or universe.get("effective_session") != (args.decision_session or args.expected_date):
            raise ValueError("O requires a complete verified official union for the decision session")
        if args.expected_date > (args.decision_session or args.expected_date):
            raise ValueError("Price session is after decision session")
    elif args.scope == "O_r0_membership_data_only":
        if not universe.get("r0_membership_verified") or universe.get("effective_session") != (args.decision_session or args.expected_date):
            raise ValueError("O R0 requires exact-session verified membership")
        if args.expected_date > (args.decision_session or args.expected_date):
            raise ValueError("Price session is after decision session")
    elif len(all_codes) != 45:
        raise ValueError("The frozen U denominator must be 45")
    codes = ["hk01810"] if args.scope == "O_single_stock_smoke" else all_codes
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if actual != args.expected_commit:
        raise ValueError("Native checkout commit mismatch")
    if subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=checkout, text=True).strip():
        raise ValueError("Native tracked code must be unchanged")
    database = output / "native-data.db"
    env = {k: v for k, v in os.environ.items() if not any(t in k.upper() for t in ("TOKEN", "API_KEY", "SECRET", "WEBHOOK"))}
    env.update(ENV_FILE="/dev/null", DATABASE_PATH=str(database), BACKTEST_ENABLED="false",
               NEWS_INTEL_AUTO_FETCH_ENABLED="false", PYTHONUNBUFFERED="1")
    command = build_native_command(checkout, codes, args.expected_date, args.target_boundary_adapter)
    audit = {"scope": args.scope, "code_commit": actual, "started_at": datetime.now(timezone.utc).isoformat(),
             "universe_sha256": hashlib.sha256(raw_universe).hexdigest(), "requested_codes": codes,
             "expected_complete_session": args.expected_date, "decision_session": args.decision_session or args.expected_date, "command": command,
             "coverage_denominator": len(codes), "O_full_union_N": len(codes) if args.scope in ("O_full_pool_data_only","O_r0_membership_data_only") else None, "O_full_pool_passed": False,
             "model_credentials_provided": False, "model_analysis_enabled": False,
             "native_logic_modified": False, "target_boundary_adapter": bool(args.target_boundary_adapter),
             "adapter_scope": "Yahoo retrieval boundary/materialization only" if args.target_boundary_adapter else None,
             "independent_price_validation": False}
    try:
        with (output / "native.log").open("w") as log:
            process = subprocess.Popen(command, cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                audit["returncode"] = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                audit.update(returncode=process.returncode, timeout=True)
    except Exception as exc:
        audit["error"] = type(exc).__name__ + ": " + str(exc)
    audit["coverage"] = audit_database(database, codes, args.expected_date)
    try:
        audit['market_history_sha256']=export_market_history(database,codes,args.expected_date,output/'market-history.json')
    except Exception as exc:
        audit['market_history_export_error']=type(exc).__name__+': '+str(exc)
    if (output / "native.log").exists():
        native_log = (output / "native.log").read_text(errors="replace")
        for record in audit["coverage"]:
            record["native_log_mentions_code"] = record["code"].lower() in native_log.lower()
        audit["target_boundary_adapter_apply_count"] = (
            int(native_log.rsplit("O_TARGET_BOUNDARY_ADAPTER_COUNT", 1)[1].strip().split()[0])
            if "O_TARGET_BOUNDARY_ADAPTER_COUNT" in native_log else 0
        )
        print("NATIVE_LOG_TAIL", native_log[-12000:], flush=True)
    audit["current_valid_count"] = sum(r["status"] == "current_valid_bar" for r in audit["coverage"])
    audit["completed_at"] = datetime.now(timezone.utc).isoformat()
    audit["status"] = "data_acquisition_complete" if audit["current_valid_count"] == len(codes) else "partial_or_failed"
    for name in ["native.log", "native-data.db"]:
        if (output / name).exists():
            audit[name + "_sha256"] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / "coverage.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print("NATIVE_DATA_COVERAGE", json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
