"""Fail-closed successor Gate-A contract for a versioned release view.

This contract never rewrites or re-labels the frozen raw pipeline result.  It
permits a release-view successor only for the narrowly proven integration defect
where the raw pipeline contract is otherwise valid and blocked solely by SEM-001
numeric ``current_price`` labels that the release quote adapter can safely clear.
"""
from __future__ import annotations

from copy import deepcopy

from o_release_quote_semantics import VERSION as RELEASE_VERSION

VERSION = "O_RELEASE_GATE_CONTRACT_v1"
ALLOWED_RAW_BLOCKERS = {"SEM-001"}
ALLOWED_RAW_SEM001_CODES = {
    "SEM001_TOPLEVEL_CURRENT_PRICE_WITHOUT_REALTIME_QUOTE",
    "SEM001_LIVE_PRICE_FIELD_WITHOUT_REALTIME_QUOTE",
}
SEM_GATES = {"SEM-001", "SEM-002", "SEM-003"}


class ReleaseGateError(ValueError):
    pass


def evaluate_release_gate(raw_post_output_contract, release_bundle):
    if not isinstance(raw_post_output_contract, dict) or not isinstance(release_bundle, dict):
        raise ReleaseGateError("RELEASE_GATE_INPUT_NOT_MAPPING")
    raw = deepcopy(raw_post_output_contract)
    bundle = deepcopy(release_bundle)
    receipt = bundle.get("receipt")
    release_audit = bundle.get("release_audit")
    if not isinstance(receipt, dict) or not isinstance(release_audit, dict):
        raise ReleaseGateError("RELEASE_GATE_RECEIPT_OR_AUDIT_MISSING")
    if receipt.get("version") != RELEASE_VERSION or receipt.get("release_status") != "PASS":
        raise ReleaseGateError("RELEASE_QUOTE_ADAPTER_NOT_PASSED")
    if receipt.get("raw_pipeline_result_mutated") is not False or receipt.get("strategy_fields_changed") is not False:
        raise ReleaseGateError("RELEASE_ADAPTER_INVARIANT_FAILED")
    if raw.get("capture_verified") is not True:
        raise ReleaseGateError("RAW_FINAL_CAPTURE_NOT_VERIFIED")
    if (raw.get("evidence_handoff") or {}).get("status") != "PASS":
        raise ReleaseGateError("RAW_EVIDENCE_HANDOFF_NOT_PASSED")
    if (raw.get("session_fact_handoff") or {}).get("status") != "PASS":
        raise ReleaseGateError("RAW_SESSION_FACT_HANDOFF_NOT_PASSED")

    raw_blockers = list((raw.get("promotion_gate") or {}).get("blockers") or [])
    if not raw_blockers or set(raw_blockers) - ALLOWED_RAW_BLOCKERS:
        raise ReleaseGateError("RAW_BLOCKER_NOT_RELEASE_SANITIZABLE")
    raw_sem001 = [f for f in ((raw.get("semantic_audit") or {}).get("findings") or [])
                  if f.get("guard_id") == "SEM-001"]
    raw_codes = {str(f.get("code")) for f in raw_sem001}
    if not raw_codes or raw_codes - ALLOWED_RAW_SEM001_CODES:
        raise ReleaseGateError("RAW_SEM001_CODE_NOT_RELEASE_SANITIZABLE")

    raw_formal = raw.get("formal_semantic_gates") or {}
    if raw_formal.get("SEM-002") != "PASS" or raw_formal.get("SEM-003") != "PASS":
        raise ReleaseGateError("RAW_OTHER_SEMANTIC_GATE_NOT_PASSED")

    release_guards = set(release_audit.get("triggered_semantic_guards") or []) & SEM_GATES
    if release_guards:
        raise ReleaseGateError("RELEASE_VIEW_SEMANTIC_GATE_REMAINS:" + ",".join(sorted(release_guards)))
    if receipt.get("release_sem001_codes") not in ([], None):
        raise ReleaseGateError("RELEASE_SEM001_RECEIPT_NOT_CLEAR")
    if not receipt.get("sanitized_paths"):
        raise ReleaseGateError("RELEASE_ADAPTER_DID_NOT_MAKE_A_PROVEN_CHANGE")

    return {
        "schema_version": 1,
        "version": VERSION,
        "status": "PASS_WITH_VERSIONED_RELEASE_ADAPTER",
        "raw_native_pipeline_semantic_pass": False,
        "raw_native_pipeline_preserved": True,
        "raw_blockers_preserved": raw_blockers,
        "release_adapter_version": RELEASE_VERSION,
        "release_view_semantic_pass": True,
        "release_sanitized_paths": list(receipt.get("sanitized_paths") or []),
        "strategy_fields_changed": False,
        "frozen_upstream_mutated": False,
        "model_requests": 0,
        "gate_a_successor_candidate": True,
        "gate_b_permitted": False,
        "gate_c_permitted": False,
        "o_full_pool_permitted": False,
        "runtime_activated": False,
    }
