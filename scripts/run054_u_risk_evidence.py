#!/usr/bin/env python3
"""Build the Run054 U45 source-bound risk/missingness receipt.

This is deterministic evidence binding only. It does not call an LLM, invent
company/sector risks, rank members, or create BUY signals. Missing evidence is
kept explicit so a later formal strategy decision can fail closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def index_by_code(rows: list[dict[str, Any]], key: str = "code") -> dict[str, dict[str, Any]]:
    return {str(row[key]).zfill(5): row for row in rows if row.get(key) is not None}


def build_receipt(
    *,
    close_refresh: dict[str, Any],
    member_reports: dict[str, Any],
    handoff: dict[str, Any],
    review_acceptance: dict[str, Any],
    macro_cap: dict[str, Any],
) -> dict[str, Any]:
    target = close_refresh["target_session"]
    if target != macro_cap["target_session"]:
        raise ValueError("close refresh and macro cap target sessions differ")

    close_rows = index_by_code(close_refresh.get("facts", []))
    reports = index_by_code(member_reports.get("members", []))
    handoff_rows = index_by_code(handoff.get("rows", []))

    accepted_reviews = {str(c).zfill(5) for c in review_acceptance.get("accepted_codes", [])}
    isolated_reviews = {
        str(x["code"]).zfill(5): str(x["reason"])
        for x in review_acceptance.get("isolated", [])
    }
    ineligible = {str(c).zfill(5) for c in review_acceptance.get("ineligible_codes", [])}

    universe_codes = sorted(close_rows)
    if len(universe_codes) != 45:
        raise ValueError(f"expected 45 close-refresh members, got {len(universe_codes)}")

    out_rows: list[dict[str, Any]] = []
    counts = {
        "denominator": 45,
        "eligible": 0,
        "ineligible_retained": 0,
        "current_bar_valid": 0,
        "bounded_member_report_present": 0,
        "news_retrieval_ready": 0,
        "verified_issuer_event_present": 0,
        "capital_verified": 0,
        "capital_not_disclosed_in_top10": 0,
        "primary_issuer_reviewed": 0,
        "qualitative_review_raw_pass": 0,
        "qualitative_review_isolated": 0,
        "sector_risk_separately_source_bound": 0,
        "formal_decision_input_pass_with_missingness": 0,
    }

    for code in universe_codes:
        close_row = close_rows[code]
        report = reports.get(code)
        hrow = handoff_rows.get(code)

        eligible = bool(hrow and hrow.get("current_buy_eligible")) and code not in ineligible
        if eligible:
            counts["eligible"] += 1
        else:
            counts["ineligible_retained"] += 1

        current_valid = bool(close_row.get("current_valid_bar"))
        counts["current_bar_valid"] += int(current_valid)
        counts["bounded_member_report_present"] += int(report is not None)

        news = (report or {}).get("news") or {}
        capital = (report or {}).get("capital") or {}
        news_ready = bool(news.get("retrieval_ready"))
        verified_urls = [u for u in news.get("verified_source_urls", []) if u]
        capital_status = str(capital.get("status") or "MISSING")
        primary_reviewed = bool(hrow and hrow.get("reviewed_issuer_primary_evidence"))

        counts["news_retrieval_ready"] += int(news_ready)
        counts["verified_issuer_event_present"] += int(bool(verified_urls))
        counts["capital_verified"] += int(capital_status == "VERIFIED")
        counts["capital_not_disclosed_in_top10"] += int(capital_status == "NOT_DISCLOSED_IN_TOP10")
        counts["primary_issuer_reviewed"] += int(primary_reviewed)

        if code in accepted_reviews:
            review_state = "RAW_SEMANTIC_PASS"
            counts["qualitative_review_raw_pass"] += 1
        elif code in isolated_reviews:
            review_state = f"RAW_SEMANTIC_ISOLATED:{isolated_reviews[code]}"
            counts["qualitative_review_isolated"] += 1
        elif code in ineligible:
            review_state = "INELIGIBLE_RETAINED"
        else:
            review_state = "REVIEW_STATUS_MISSING"

        if verified_urls:
            company_event_state = "VERIFIED_BOUNDED_ISSUER_EVENT"
        elif news_ready:
            company_event_state = "NO_VERIFIED_RECENT_EVENT_IN_BOUNDED_SEARCH_NOT_NO_RISK"
        else:
            company_event_state = "NEWS_EVIDENCE_MISSING"

        # Existing accepted public receipts do not provide a separately sourced
        # sector-risk record per member. Keep this missingness explicit rather
        # than converting a company/news observation into sector evidence.
        sector_state = "NOT_SEPARATELY_SOURCE_BOUND"

        if not eligible:
            formal_input = "INELIGIBLE_RETAINED_NO_FORMAL_BUY_DECISION"
        elif current_valid and report is not None and hrow is not None and review_state != "REVIEW_STATUS_MISSING":
            formal_input = "PASS_WITH_EXPLICIT_RISK_MISSINGNESS"
            counts["formal_decision_input_pass_with_missingness"] += 1
        else:
            formal_input = "FAIL_CLOSED_INPUT_INCOMPLETE"

        out_rows.append(
            {
                "code": code,
                "name": close_row.get("official_name") or (report or {}).get("name") or (hrow or {}).get("name"),
                "eligible": eligible,
                "current_close": close_row.get("close"),
                "current_bar_valid": current_valid,
                "member_report_available": report is not None,
                "company_event_evidence": {
                    "state": company_event_state,
                    "retrieval_ready": news_ready,
                    "verified_source_urls": verified_urls,
                    "bounded_scope": news.get("scope"),
                },
                "capital_evidence": {
                    "state": capital_status,
                    "net_buy_hkd": capital.get("net_buy_hkd"),
                    "channel_coverage": capital.get("channel_coverage"),
                    "source_locator": capital.get("source_locator"),
                    "source_sha256": capital.get("source_sha256"),
                    "date": capital.get("date"),
                    "persistence": capital.get("persistence"),
                    "ultimate_investor_identity": capital.get("ultimate_investor_identity"),
                },
                "issuer_primary_review": {
                    "reviewed": primary_reviewed,
                    "scope": (hrow or {}).get("primary_review_scope"),
                    "full_risk_coverage_proven": bool(hrow and hrow.get("full_risk_coverage_proven")),
                },
                "sector_risk_evidence": {
                    "state": sector_state,
                    "rule": "Do not infer sector risk from company-news absence, price action, or unsourced model prose.",
                },
                "qualitative_review": {
                    "state": review_state,
                    "source_run": review_acceptance.get("run_id"),
                    "is_full_strategy_decision": False,
                },
                "formal_decision_input_status": formal_input,
                "buy_permission_from_run054": False,
            }
        )

    if counts["eligible"] != 44 or counts["ineligible_retained"] != 1:
        raise ValueError(f"unexpected eligibility counts: {counts}")

    return {
        "schema_version": 1,
        "run_id": "TRI-DSA-RESUME-20260917-054",
        "target_session": target,
        "scope": "Freeze source-bound U45 company-event/capital evidence and explicit company/sector risk missingness. Deterministic only; no ranking, BUY, quote or fill inference.",
        "inputs": {
            "close_refresh_run": close_refresh.get("run_id"),
            "member_report_run": member_reports.get("run_id"),
            "handoff_run": handoff.get("run_id"),
            "review_acceptance_run": review_acceptance.get("run_id"),
            "macro_cap_run": macro_cap.get("run_id"),
        },
        "evidence_contract": {
            "verified_event_requires_source_url": True,
            "bounded_search_no_hit_is_not_no_adverse_news": True,
            "capital_not_disclosed_in_top10_is_not_zero_flow": True,
            "ultimate_investor_identity_not_inferred": True,
            "sector_risk_requires_separate_source": True,
            "missingness_must_survive_into_formal_strategy_prompt": True,
            "formal_strategy_may_return_WAIT_when_risk_evidence_is_incomplete": True,
            "BUY_must_not_be_created_by_this_run": True,
        },
        "macro_position_ceiling_pct": macro_cap.get("regime", {}).get("position_ceiling_pct"),
        "counts": counts,
        "rows": out_rows,
        "result": {
            "status": "PASS_RISK_EVIDENCE_BINDING_WITH_EXPLICIT_MISSINGNESS",
            "risk_evidence_bound": True,
            "risk_evidence_complete_for_all_members": False,
            "formal_decision_inputs_available_with_missingness": counts["formal_decision_input_pass_with_missingness"],
            "qualified_BUY_created": 0,
            "ranking_created": False,
            "simulation_authorized": False,
        },
        "resources": {
            "model_http_requests": 0,
            "paid_data_calls": 0,
            "real_orders": 0,
            "schedule_changes": 0,
        },
        "next": "RUN055: bind a strategy buy-zone contract without inventing execution quotes. RUN056 may consume RUN053-055 only after each contract passes; missing risk remains explicit input and may force WAIT.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--close-refresh", required=True)
    ap.add_argument("--member-reports", required=True)
    ap.add_argument("--handoff", required=True)
    ap.add_argument("--review-acceptance", required=True)
    ap.add_argument("--macro-cap", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    receipt = build_receipt(
        close_refresh=load(args.close_refresh),
        member_reports=load(args.member_reports),
        handoff=load(args.handoff),
        review_acceptance=load(args.review_acceptance),
        macro_cap=load(args.macro_cap),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["result"]["status"], "counts": receipt["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
