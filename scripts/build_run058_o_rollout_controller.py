"""Run058 zero-model resumable controller for the O608 native rollout.

This module never calls a provider and never mutates Drive. It binds the accepted
Run057 rollout plan, reconciles only the sanitized public rollout ledger, and emits
at most one child launch envelope. Durable Drive claims remain the source of truth
inside the paid child runner immediately before any send.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

RUN_ID = "TRI-DSA-RESUME-20260917-058"
READY_STATE = "READY_CHILD_ENVELOPE"
HOLD_STATE = "HOLD_NO_CHILD"
TERMINAL_BATCH_STATES = {"ACCEPTED_NATIVE", "RAW_GATE_BLOCK"}
HOLD_BATCH_STATES = {
    "CLAIMED_RECONCILE",
    "PRIVATE_PRESEND_FAIL",
    "BALANCE_FAIL",
    "PROVIDER_FAIL_AFTER_CLAIM",
    "PRIVATE_FINAL_FAIL",
    "STOP_TRANCHE",
}
ALLOWED_LEDGER_STATES = TERMINAL_BATCH_STATES | HOLD_BATCH_STATES


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw)


def read_jsonl(path: Path):
    if not path.exists():
        return [], None
    raw = path.read_bytes()
    rows = []
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"BAD_LEDGER_JSON_LINE:{n}") from exc
    return rows, sha256_bytes(raw)


def validate_plan(plan: dict, scope: dict) -> None:
    counts = scope["frozen_counts"]
    if plan.get("state") != "PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN":
        raise ValueError("RUN057_PLAN_NOT_ACCEPTED")
    d = plan.get("denominator") or {}
    if d.get("O_universe") != counts["O_universe"]:
        raise ValueError("O_DENOMINATOR_CHANGED")
    if d.get("deterministic_ready") != counts["deterministic_ready"]:
        raise ValueError("O_READY_COUNT_CHANGED")
    if d.get("retained_isolated") != counts["retained_isolated"]:
        raise ValueError("O_ISOLATED_COUNT_CHANGED")
    no_repeat = plan.get("no_repeat") or {}
    if no_repeat.get("count_within_ready") != counts["no_repeat_ready"]:
        raise ValueError("NO_REPEAT_COUNT_CHANGED")
    rollout = plan.get("rollout") or {}
    if rollout.get("never_called_count") != counts["never_called"]:
        raise ValueError("NEVER_CALLED_COUNT_CHANGED")
    if rollout.get("micro_batch_count") != counts["micro_batch_count"]:
        raise ValueError("MICROBATCH_COUNT_CHANGED")
    if rollout.get("tranche_count") != counts["planning_tranche_count"]:
        raise ValueError("TRANCHE_COUNT_CHANGED")
    if rollout.get("micro_batch_width") != 2:
        raise ValueError("UNPROVEN_MICROBATCH_WIDTH")
    if rollout.get("send_authorized_by_run057") is not False:
        raise ValueError("RUN057_MUST_NOT_AUTHORIZE_SEND")


def validate_ledger(rows: list[dict], plan: dict) -> dict[str, dict]:
    plan_batches = {x["micro_batch_id"]: x for x in plan["rollout"]["micro_batches"]}
    latest = {}
    for i, row in enumerate(rows):
        batch_id = row.get("micro_batch_id")
        status = row.get("status")
        if batch_id not in plan_batches:
            raise ValueError(f"LEDGER_UNKNOWN_BATCH:{batch_id}")
        if status not in ALLOWED_LEDGER_STATES:
            raise ValueError(f"LEDGER_BAD_STATUS:{status}")
        expected = plan_batches[batch_id]["codes"]
        if row.get("codes") != expected:
            raise ValueError(f"LEDGER_CODE_MISMATCH:{batch_id}")
        prior = latest.get(batch_id)
        if prior is not None:
            # Append-only corrections may add detail, but a completed or hold state
            # cannot silently flip to a different semantic state.
            if prior.get("status") != status:
                raise ValueError(f"LEDGER_CONFLICTING_STATE:{batch_id}")
        latest[batch_id] = {**row, "_line_index": i}
    return latest


def tranche_for_batch(plan: dict, batch_id: str) -> dict:
    matches = [t for t in plan["rollout"]["tranches"] if batch_id in t["micro_batch_ids"]]
    if len(matches) != 1:
        raise ValueError(f"TRANCHE_BINDING_FAIL:{batch_id}")
    return matches[0]


def build(plan: dict, scope: dict, ledger_rows: list[dict], plan_sha: str, ledger_sha: str | None) -> dict:
    validate_plan(plan, scope)
    latest = validate_ledger(ledger_rows, plan)
    never_called = set(plan["rollout"]["never_called_codes"])
    isolated = set(plan["isolation"]["codes"])
    no_repeat = set(plan["no_repeat"]["spent_codes_within_ready"])
    forbidden = isolated | no_repeat

    # Any unresolved hold is deliberately global for Run058. The next controller
    # revision may only continue after an append-only reconciliation receipt.
    unresolved_holds = [
        {"micro_batch_id": bid, "status": row["status"], "codes": row["codes"]}
        for bid, row in latest.items()
        if row["status"] in HOLD_BATCH_STATES
    ]
    if unresolved_holds:
        unresolved_holds.sort(key=lambda x: x["micro_batch_id"])
        return {
            "schema_version": 1,
            "run_id": RUN_ID,
            "state": HOLD_STATE,
            "target_session": scope["target_session"],
            "reason": "UNRESOLVED_FAIL_CLOSED_LEDGER_STATE",
            "holds": unresolved_holds,
            "selected_child": None,
            "plan_sha256": plan_sha,
            "ledger_sha256": ledger_sha,
            "resource_accounting": scope["resource_plan"],
            "next": "Append a verified reconciliation receipt; do not retry a claimed or private-failure batch automatically.",
        }

    selected = None
    for batch in plan["rollout"]["micro_batches"]:
        batch_id = batch["micro_batch_id"]
        if batch_id in latest and latest[batch_id]["status"] in TERMINAL_BATCH_STATES:
            continue
        codes = batch["codes"]
        if len(codes) not in (1, 2):
            raise ValueError(f"BAD_BATCH_WIDTH:{batch_id}")
        if not set(codes) <= never_called:
            raise ValueError(f"BATCH_NOT_NEVER_CALLED:{batch_id}")
        if set(codes) & forbidden:
            raise ValueError(f"BATCH_CONTAINS_FORBIDDEN_CODE:{batch_id}")
        selected = batch
        break

    if selected is None:
        return {
            "schema_version": 1,
            "run_id": RUN_ID,
            "state": HOLD_STATE,
            "target_session": scope["target_session"],
            "reason": "ALL_RUN057_NEVER_CALLED_BATCHES_TERMINAL",
            "holds": [],
            "selected_child": None,
            "plan_sha256": plan_sha,
            "ledger_sha256": ledger_sha,
            "resource_accounting": scope["resource_plan"],
            "next": "Proceed to full O pool reconciliation/ranking only after all accepted child receipts are bound; retained isolates remain in denominator.",
        }

    tranche = tranche_for_batch(plan, selected["micro_batch_id"])
    child = scope["child_contract"]
    cap = f"{0.10 * len(selected['codes']):.2f}"
    if cap != selected["hard_cap_cny"] or cap != child["child_hard_cap_cny"]:
        raise ValueError("CHILD_COST_CAP_MISMATCH")

    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "state": READY_STATE,
        "target_session": scope["target_session"],
        "plan_sha256": plan_sha,
        "ledger_sha256": ledger_sha,
        "denominator": {
            "O_universe": 660,
            "deterministic_ready": 608,
            "retained_isolated": 52,
            "no_repeat_ready": 3,
            "never_called": 605,
        },
        "ledger_summary": {
            "rows": len(ledger_rows),
            "terminal_batches": sum(r["status"] in TERMINAL_BATCH_STATES for r in latest.values()),
            "hold_batches": 0,
        },
        "selected_child": {
            "proposed_child_run_id": child["proposed_child_run_id"],
            "micro_batch_id": selected["micro_batch_id"],
            "tranche_id": tranche["tranche_id"],
            "codes": selected["codes"],
            "member_count": len(selected["codes"]),
            "per_member_hard_cap_cny": child["per_member_hard_cap_cny"],
            "child_hard_cap_cny": cap,
            "native_model_configuration": child["native_model_configuration"],
            "required_pre_send_gates": child["required_pre_send_gates"],
            "required_post_send_gates": child["required_post_send_gates"],
            "drive_claim_reconciliation_required_before_send": True,
            "automatic_retry_after_claim": False,
            "provider_send_authorized_by_run058": False,
        },
        "resource_accounting": scope["resource_plan"],
        "next": "Create one immutable paid-child scope for only this selected micro-batch. The child must re-run free preflight and Drive claim reconciliation before any provider request. Do not arm the next micro-batch until this child is reconciled.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    scope, _ = read_json(args.scope)
    if scope.get("run_id") != RUN_ID:
        raise ValueError("RUN058_SCOPE_MISMATCH")
    if scope.get("resource_plan", {}).get("model_http_requests") != 0:
        raise ValueError("RUN058_MUST_BE_ZERO_MODEL")
    plan, plan_sha = read_json(args.plan)
    ledger_rows, ledger_sha = read_jsonl(args.ledger)
    result = build(plan, scope, ledger_rows, plan_sha, ledger_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "selected_child": result.get("selected_child"),
        "model_http_requests": 0,
        "paid_data_calls": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
