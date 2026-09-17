from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CONTRACT_ID = "U45_STRATEGY_BUY_ZONE_v1"
ALLOWED_ZONE_STATUS = {"WITHHELD_UNKNOWN", "PENDING_FORMAL_DECISION", "APPROVED_NUMERIC"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw)


def validate_zone_row(row: dict) -> None:
    status = row["zone_status"]
    if status not in ALLOWED_ZONE_STATUS:
        raise ValueError("BAD_ZONE_STATUS")
    if row.get("execution_quote_used_to_construct_zone") is not False:
        raise ValueError("EXECUTION_QUOTE_MUST_NOT_CONSTRUCT_STRATEGY_ZONE")
    if row.get("later_price_move_can_widen_zone") is not False:
        raise ValueError("LATER_PRICE_WIDENING_FORBIDDEN")
    if status == "APPROVED_NUMERIC":
        lo, hi = row.get("lower"), row.get("upper")
        if lo is None or hi is None or not (0 < float(lo) <= float(hi)):
            raise ValueError("NUMERIC_ZONE_INVALID")
        if not row.get("formal_strategy_decision_id") or not row.get("rationale"):
            raise ValueError("NUMERIC_ZONE_NEEDS_FORMAL_DECISION_AND_RATIONALE")
        if not row.get("source_evidence"):
            raise ValueError("NUMERIC_ZONE_NEEDS_SOURCE_EVIDENCE")
    else:
        if row.get("lower") is not None or row.get("upper") is not None:
            raise ValueError("WITHHELD_OR_PENDING_ZONE_MUST_NOT_HAVE_NUMERIC_BOUNDS")


def build(facts: dict, handoff: dict, macro: dict, risk: dict) -> dict:
    risk_rows = risk.get("rows", [])
    if len(risk_rows) != 45:
        raise ValueError("U45_DENOMINATOR_NOT_45")
    seen = {str(r["code"]).zfill(5) for r in risk_rows}
    if len(seen) != 45:
        raise ValueError("U45_CODE_DUPLICATE_OR_MISSING")
    macro_cap = macro.get("regime", {}).get("position_ceiling_pct")
    if macro_cap != 30:
        raise ValueError("RUN053_MACRO_CAP_MISMATCH")

    rows = []
    for r in risk_rows:
        code = str(r["code"]).zfill(5)
        eligible = bool(r.get("eligible"))
        risk_missing = (
            r.get("sector_risk_evidence", {}).get("state") != "SOURCE_BOUND"
            and r.get("sector_risk_evidence", {}).get("state") != "SEPARATELY_SOURCE_BOUND"
        ) or not r.get("issuer_primary_review", {}).get("full_risk_coverage_proven", False)
        if not eligible:
            status = "WITHHELD_UNKNOWN"
            reason = "INELIGIBLE_RETAINED_IN_DENOMINATOR"
        else:
            status = "PENDING_FORMAL_DECISION"
            reason = "FORMAL_STRATEGY_DECISION_REQUIRED"
            if risk_missing:
                reason += ";RISK_MISSINGNESS_MUST_REMAIN_EXPLICIT"
        row = {
            "code": code,
            "name": r.get("name"),
            "eligible": eligible,
            "zone_status": status,
            "lower": None,
            "upper": None,
            "currency": "HKD",
            "formal_strategy_decision_id": None,
            "rationale": None,
            "source_evidence": [],
            "risk_missingness_explicit": risk_missing,
            "macro_position_ceiling_pct": macro_cap,
            "macro_cap_changes_score_or_rank": False,
            "execution_quote_used_to_construct_zone": False,
            "later_price_move_can_widen_zone": False,
            "entry_v1_band_applied_at_strategy_zone_stage": False,
            "future_executable_range_rule": "INTERSECTION_OF_APPROVED_STRATEGY_ZONE_AND_ENTRY_V1_BAND_AT_EXECUTION_HANDOFF",
            "reason": reason,
            "buy_permission_from_run055": False,
        }
        validate_zone_row(row)
        rows.append(row)

    ineligible = sorted(r["code"] for r in rows if not r["eligible"])
    if ineligible != ["09618"]:
        raise ValueError("EXPECTED_09618_ONLY_INELIGIBLE")

    return {
        "schema_version": 1,
        "run_id": "TRI-DSA-RESUME-20260917-055",
        "contract_id": CONTRACT_ID,
        "target_session": "2026-09-17",
        "state": "PASS_CONTRACT_ONLY_FORMAL_MEMBER_ZONES_PENDING_RUN056",
        "denominator": 45,
        "eligible": 44,
        "retained_ineligible": ineligible,
        "macro_position_ceiling_pct": macro_cap,
        "contract": {
            "strategy_zone_distinct_from_entry_v1_band": True,
            "strategy_zone_distinct_from_firm_ask": True,
            "numeric_zone_requires_formal_strategy_decision": True,
            "numeric_zone_requires_source_bound_inputs": True,
            "missing_support_or_risk_evidence": "WITHHOLD_NUMERIC_ZONE_OR_FORMAL_DECISION_MAY_RETURN_WATCH_BLOCKED_DATA",
            "future_quote_may_not_construct_or_widen_zone": True,
            "entry_v1_intersection_occurs_only_after_strategy_zone_approval": True,
            "macro_cap_is_exposure_overlay_not_score_override": True,
            "run055_creates_buy": False,
            "run055_creates_rank": False,
        },
        "counts": {
            "members": len(rows),
            "approved_numeric_zones": sum(r["zone_status"] == "APPROVED_NUMERIC" for r in rows),
            "pending_formal_decision": sum(r["zone_status"] == "PENDING_FORMAL_DECISION" for r in rows),
            "withheld_unknown": sum(r["zone_status"] == "WITHHELD_UNKNOWN" for r in rows),
            "risk_missingness_explicit": sum(r["risk_missingness_explicit"] for r in rows),
            "qualified_buy_created": 0,
        },
        "rows": rows,
        "resource_accounting": {
            "model_http_requests": 0,
            "paid_data_calls": 0,
            "DeepSeek_API_cost_cny": 0,
            "actual_charge_cny": 0,
            "real_orders": 0,
            "shadow_signal_writes": 0,
            "shadow_simulation_writes": 0,
        },
        "next": "RUN056 may perform formal U45 strategy decisions and ranking using RUN053 macro cap, RUN054 risk evidence and this contract. Numeric zones may be created only inside that accepted formal-decision path; BUY=0 remains valid.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", type=Path, required=True)
    ap.add_argument("--handoff", type=Path, required=True)
    ap.add_argument("--macro", type=Path, required=True)
    ap.add_argument("--risk", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    facts, facts_sha = read_json(args.facts)
    handoff, handoff_sha = read_json(args.handoff)
    macro, macro_sha = read_json(args.macro)
    risk, risk_sha = read_json(args.risk)
    result = build(facts, handoff, macro, risk)
    result["input_sha256"] = {
        str(args.facts): facts_sha,
        str(args.handoff): handoff_sha,
        str(args.macro): macro_sha,
        str(args.risk): risk_sha,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
