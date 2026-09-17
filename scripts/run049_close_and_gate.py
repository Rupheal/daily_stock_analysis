#!/usr/bin/env python3
"""Run049 deterministic close refresh + U formal gate + O52 current-session audit.

This module never invents U scores/ranks, macro caps or buy zones.  It consumes
accepted/native data-acquisition artifacts and fails closed when a formally
accepted strategy contract is absent.  O52 current-session availability is
reported separately from historical multi-source conflict resolution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TARGET = "2026-09-17"
RUN_ID = "TRI-DSA-RESUME-20260917-049"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code5(value):
    s = str(value).lower()
    return s[2:] if s.startswith("hk") else s


def coverage_map(coverage, target, denominator):
    if coverage.get("expected_complete_session") != target:
        raise ValueError("STALE_OR_WRONG_TARGET_SESSION")
    if int(coverage.get("coverage_denominator", -1)) != denominator:
        raise ValueError("COVERAGE_DENOMINATOR_MISMATCH")
    rows = coverage.get("coverage") or []
    if len(rows) != denominator:
        raise ValueError("COVERAGE_ROW_COUNT_MISMATCH")
    out = {}
    for row in rows:
        c = code5(row.get("code"))
        if c in out:
            raise ValueError("DUPLICATE_COVERAGE_CODE:" + c)
        out[c] = row
    return out


def universe_members(universe, denominator):
    rows = universe.get("members") or []
    if universe.get("member_count") != denominator or len(rows) != denominator:
        raise ValueError("UNIVERSE_DENOMINATOR_MISMATCH")
    codes = [code5(x["code"]) for x in rows]
    if len(set(codes)) != denominator:
        raise ValueError("UNIVERSE_DUPLICATE_CODE")
    return rows


def build_u_refresh(universe, coverage, target=TARGET):
    members = universe_members(universe, 45)
    cov = coverage_map(coverage, target, 45)
    facts = []
    for member in members:
        c = code5(member["code"])
        r = cov.get(c)
        if r is None:
            raise ValueError("MISSING_U_COVERAGE_CODE:" + c)
        current = r.get("status") == "current_valid_bar" and r.get("latest_date") == target
        ohlcv = r.get("latest_ohlcv") if current else None
        facts.append({
            "code": c,
            "official_name": member.get("official_name"),
            "english_name": member.get("english_name"),
            "target_session": target,
            "current_valid_bar": current,
            "latest_date": r.get("latest_date"),
            "open": ohlcv[0] if ohlcv else None,
            "high": ohlcv[1] if ohlcv else None,
            "low": ohlcv[2] if ohlcv else None,
            "close": ohlcv[3] if ohlcv else None,
            "volume": ohlcv[4] if ohlcv else None,
            "native_log_mentions_code": r.get("native_log_mentions_code"),
        })
    ready = sum(x["current_valid_bar"] for x in facts)
    return {
        "schema": "dsa-run049-u45-close-refresh-v1",
        "run_id": RUN_ID,
        "target_session": target,
        "denominator": 45,
        "current_valid_count": ready,
        "status": "PASS_CURRENT_SESSION_FACT_REFRESH" if ready == 45 else "PARTIAL_CURRENT_SESSION_FACT_REFRESH",
        "facts": facts,
        "boundary": "Native acquisition fact refresh only; not independent price validation and not a strategy signal.",
    }


def old_o52(prior):
    if prior.get("O_denominator") != 660 or prior.get("isolated") != 52:
        raise ValueError("RUN045_O52_BASELINE_MISMATCH")
    rows = [x for x in (prior.get("checks") or []) if x.get("status") == "ISOLATED"]
    if len(rows) != 52:
        raise ValueError("RUN045_ISOLATED_ROWS_NOT_52")
    return rows


def build_o52_audit(prior, o_coverage, target=TARGET):
    old = old_o52(prior)
    cov = coverage_map(o_coverage, target, 660)
    rows = []
    for p in old:
        c = code5(p["code"])
        r = cov.get(c)
        current = bool(r and r.get("status") == "current_valid_bar" and r.get("latest_date") == target)
        rows.append({
            "code": c,
            "prior_isolation_reason": p.get("reason") or "UNSPECIFIED_PRIOR_ISOLATION",
            "prior_status": "ISOLATED",
            "current_session_data_ready": current,
            "current_latest_date": r.get("latest_date") if r else None,
            "current_status": r.get("status") if r else "missing",
            "historical_source_conflict_resolved": False,
            "release_to_original_ranking_chain": False,
            "note": "A current native bar cannot erase a previously accepted multi-source/history isolation without matching independent reconciliation evidence.",
        })
    current_ready = sum(x["current_session_data_ready"] for x in rows)
    return {
        "schema": "dsa-run049-o52-current-session-audit-v1",
        "run_id": RUN_ID,
        "target_session": target,
        "O_denominator": 660,
        "prior_ready": 608,
        "prior_isolated": 52,
        "reviewed_prior_isolations": 52,
        "current_session_data_ready_within_o52": current_ready,
        "current_session_still_not_ready_within_o52": 52 - current_ready,
        "historical_source_conflicts_resolved_this_run": 0,
        "released_to_original_ranking_chain_this_run": 0,
        "prior_reason_counts": dict(Counter(x["prior_isolation_reason"] for x in rows)),
        "rows": rows,
        "status": "PASS_BOUNDED_CURRENT_SESSION_REVIEW_NO_HISTORICAL_RELEASE",
    }


def build_u_gate(u_refresh, handoff, member_reports):
    # Authoritative current handoff explicitly requires separate accepted rank,
    # accepted buy-zone and verified macro cap. Run041 execution envelopes do
    # not provide those strategy authorities.
    prereq_text = json.dumps(handoff, ensure_ascii=False) + json.dumps(member_reports, ensure_ascii=False)
    required_markers = ("accepted_U_BUY_and_rank", "verified_macro_cap")
    marker_visibility = {m: (m in prereq_text) for m in required_markers}
    gate = {
        "schema": "dsa-run049-u-formal-signal-gate-v1",
        "run_id": RUN_ID,
        "target_session": TARGET,
        "denominator": 45,
        "close_refresh_status": u_refresh["status"],
        "ranking": {
            "status": "NO_GO_MISSING_ACCEPTED_RANKING_CONTRACT",
            "executed": False,
            "Top3": [],
            "Top10": [],
            "rule": "No score/rank is invented from prep, bounded observation reviews, or legacy pilot weights.",
        },
        "macro_cap": {
            "status": "NO_GO_MISSING_DATED_VERIFIED_MACRO_CAP",
            "accepted_value": None,
        },
        "buy_zone": {
            "status": "NO_GO_MISSING_ACCEPTED_STRATEGY_BUY_ZONE",
            "accepted_members": 0,
            "rule": "Entry-v1 execution envelope is not a strategy buy-zone generator.",
        },
        "formal_signal_gate": "NO_GO",
        "formal_signal_count": 0,
        "qualified_BUY": 0,
        "marker_visibility": marker_visibility,
        "authority_search": {
            "checked": [
                "docs/runtime/RUN047_U45_HANDOFF.json",
                "docs/runtime/RUN041_U45_MEMBER_REPORTS.json",
                "docs/runtime/RUN032_FORMAL_EXECUTION_SCOPE.json",
                "scripts/dsa_u_execution_audit.py",
                "scripts/run004_u45_safe_deepseek.py",
            ],
            "conclusion": "No current accepted formal ranking + dated macro-cap + strategy buy-zone contract was established in the bounded authority set; legacy pilot ranking is not promoted.",
        },
        "boundary": "Data readiness and report readiness do not imply a formal U signal.",
    }
    return gate


def write_report(out, u, gate, o, workflow_run):
    lines = [
        "# DSA Run049 报告", "",
        f"Run ID：{RUN_ID}",
        f"目标交易日：{TARGET}",
        "状态：DATA_REFRESH_COMPLETED / FORMAL_SIGNAL_NO_GO", "",
        "## U45 9/17 收盘事实刷新",
        f"- 分母：45；当日有效 bar：{u['current_valid_count']}/45。",
        "- 这是原生数据事实刷新，不等于独立价格验证，也不等于策略信号。", "",
        "## U 正式 ranking / macro cap / buy-zone",
        f"- Ranking：{gate['ranking']['status']}；未自造分数，Top3/Top10 保持空。",
        f"- Macro cap：{gate['macro_cap']['status']}。",
        f"- Buy zone：{gate['buy_zone']['status']}。",
        f"- Formal signal gate：{gate['formal_signal_gate']}；qualified BUY={gate['qualified_BUY']}。", "",
        "## O52 免费隔离审计",
        f"- 历史隔离分母：52；9/17 当前数据可用：{o['current_session_data_ready_within_o52']}/52。",
        f"- 仍缺当日数据：{o['current_session_still_not_ready_within_o52']}/52。",
        "- 历史多源冲突本轮释放：0；当前 bar 可用不覆盖旧冲突证据。", "",
        "## 资源",
        "- 新模型请求：0；付费数据调用：0；新订阅：0；真实订单：0。",
        f"- GitHub Actions Run：{workflow_run or 'UNKNOWN'}；平台实际费用：NOT_EXPOSED。", "",
        "## NEXT",
        "- U：恢复/冻结被接受的正式 ranking contract、dated macro cap、strategy buy-zone contract 后才运行 formal ranking。",
        "- O：继续对52只做独立多源全窗口 reconciliation；未解除者不得放回原生排名链。",
        "- 若 future formal signal 仍为0，Shadow execution 保持 WAIT。", "",
        "OWNER ACTION: NONE",
    ]
    Path(out, "RUN049_REPORT.zh-CN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--u-universe", required=True)
    ap.add_argument("--u-coverage", required=True)
    ap.add_argument("--u-history", required=True)
    ap.add_argument("--u-handoff", required=True)
    ap.add_argument("--u-member-reports", required=True)
    ap.add_argument("--o-coverage", required=True)
    ap.add_argument("--o-prior-third", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default=TARGET)
    args = ap.parse_args()
    if args.target != TARGET:
        raise ValueError("RUN049_TARGET_IS_FIXED_TO_2026_09_17")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    universe = load(args.u_universe); u_cov = load(args.u_coverage)
    u_history = load(args.u_history); handoff = load(args.u_handoff); reports = load(args.u_member_reports)
    o_cov = load(args.o_coverage); prior = load(args.o_prior_third)
    if u_history.get("target_session") != TARGET or u_history.get("requested_denominator") != 45:
        raise ValueError("U_HISTORY_TARGET_OR_DENOMINATOR_MISMATCH")
    u = build_u_refresh(universe, u_cov, TARGET)
    gate = build_u_gate(u, handoff, reports)
    o = build_o52_audit(prior, o_cov, TARGET)
    workflow_run = os.environ.get("GITHUB_RUN_ID")
    receipt = {
        "schema": "dsa-run049-combined-v1", "run_id": RUN_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(), "target_session": TARGET,
        "U": {"denominator":45,"current_valid_count":u["current_valid_count"],"formal_signal_gate":gate["formal_signal_gate"],"qualified_BUY":0},
        "O": {"denominator":660,"prior_isolated":52,"current_session_ready_within_prior_isolated":o["current_session_data_ready_within_o52"],"historical_released":0},
        "evidence": {
            "u_coverage_sha256": sha(args.u_coverage), "u_history_sha256": sha(args.u_history),
            "o_coverage_sha256": sha(args.o_coverage), "run045_third_source_sha256": sha(args.o_prior_third),
            "workflow_run": workflow_run, "artifact_name": "RUN049_PUBLIC_CLOSE_AND_GATE_EVIDENCE",
        },
        "resource_accounting": {"model_http_requests":0,"paid_data_calls":0,"new_subscription_spend":0,"real_orders":0,"actual_platform_cost":None,"actual_cost_status":"NOT_EXPOSED"},
        "permissions": {"main_merge":False,"schedule_changes":False,"production_promotion":False,"real_orders":0},
        "state": "CURRENT_DATA_REFRESH_ACCEPTED_FORMAL_U_SIGNAL_NO_GO_O52_NO_HISTORICAL_RELEASE",
    }
    cost = {"run_id":RUN_ID,"model_http_requests":0,"paid_data_calls":0,"new_subscription_spend":0,"github_actions_jobs":1,"actual_cost":None,"actual_cost_status":"NOT_EXPOSED"}
    dump(out/"RUN049_U45_20260917_CLOSE_REFRESH.json", u)
    dump(out/"RUN049_U_FORMAL_GATE.json", gate)
    dump(out/"RUN049_O52_REPAIR.json", o)
    dump(out/"RUN049_COMBINED_RESULT.json", receipt)
    dump(out/"RUN049_COST_LEDGER.json", cost)
    write_report(out, u, gate, o, workflow_run)
    print(json.dumps({"run_id":RUN_ID,"u_current":u["current_valid_count"],"u_gate":gate["formal_signal_gate"],"o52_current":o["current_session_data_ready_within_o52"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
