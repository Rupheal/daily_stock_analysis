"""Deterministic release-view adapter for completed-session quote semantics.

The frozen O pipeline result is preserved byte-for-byte as raw evidence.  This
module builds a separate release view only.  When the explicit Gate-A execution
contract proves realtime_quote_available=false, any numeric field whose key is
exactly ``current_price`` may be cleared only when its value is provably equal
to the target-session completed close.  Any different numeric value fails
closed.  Text is never rewritten, strategy/action fields are never changed, and
no model/network/broker call occurs here.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from o_single_output_fact_check import check_saved_output

VERSION = "O_RELEASE_QUOTE_SEMANTICS_v1"
EXECUTION_CONTRACT_VERSION = "O_GATE_A_EXECUTION_CONTRACT_v2"


class ReleaseQuoteError(ValueError):
    pass


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value):
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _semantic_001_findings(audit):
    return [f for f in (audit.get("findings") or []) if f.get("guard_id") == "SEM-001"]


def _sanitize_current_price_fields(node, *, target_close, path="$", changes=None):
    if changes is None:
        changes = []
    if isinstance(node, dict):
        for key in list(node):
            child_path = f"{path}.{key}"
            value = node[key]
            if key == "current_price":
                numeric = _number(value)
                if numeric is not None:
                    if numeric != target_close:
                        raise ReleaseQuoteError(
                            "NONREALTIME_CURRENT_PRICE_NOT_TARGET_CLOSE:" + child_path
                        )
                    node[key] = None
                    changes.append({
                        "path": child_path,
                        "source": "target_session_completed_close",
                        "original_value": str(numeric),
                        "release_value": None,
                    })
                    continue
            _sanitize_current_price_fields(value, target_close=target_close,
                                           path=child_path, changes=changes)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _sanitize_current_price_fields(value, target_close=target_close,
                                           path=f"{path}[{index}]", changes=changes)
    return changes


def build_release_view(preflight, original_input, pipeline_final):
    if not isinstance(preflight, dict) or not isinstance(original_input, dict) or not isinstance(pipeline_final, dict):
        raise ReleaseQuoteError("RELEASE_INPUT_NOT_MAPPING")
    raw_before = deepcopy(pipeline_final)
    contract = preflight.get("execution_contract")
    if not isinstance(contract, dict) or contract.get("version") != EXECUTION_CONTRACT_VERSION:
        raise ReleaseQuoteError("RELEASE_EXECUTION_CONTRACT_MISSING_OR_WRONG_VERSION")
    realtime = contract.get("realtime_quote_available")
    if type(realtime) is not bool:
        raise ReleaseQuoteError("RELEASE_REALTIME_AVAILABILITY_NOT_BOOLEAN")
    target = str(preflight.get("target") or "")
    if not target or str(contract.get("target_session") or "") != target:
        raise ReleaseQuoteError("RELEASE_TARGET_SESSION_MISMATCH")

    raw_audit = check_saved_output(preflight, original_input, pipeline_final)
    release = deepcopy(pipeline_final)
    changes = []

    if realtime is False:
        today = preflight.get("today") or {}
        close = _number(today.get("close"))
        if close is None or close <= 0:
            raise ReleaseQuoteError("RELEASE_TARGET_CLOSE_UNPROVEN")
        changes = _sanitize_current_price_fields(release, target_close=close)
    else:
        close = None

    release_audit = check_saved_output(preflight, original_input, release)
    remaining_sem001 = _semantic_001_findings(release_audit)
    if remaining_sem001:
        codes = sorted({str(f.get("code")) for f in remaining_sem001})
        raise ReleaseQuoteError("RELEASE_SEM001_REMAINS:" + ",".join(codes))

    if pipeline_final != raw_before:
        raise AssertionError("RAW_PIPELINE_RESULT_MUTATED")

    protected = ("action", "operation_advice", "decision_type", "sentiment_score",
                 "analysis_summary", "pattern_analysis")
    changed_strategy = [key for key in protected if release.get(key) != pipeline_final.get(key)]
    if changed_strategy:
        raise AssertionError("RELEASE_STRATEGY_FIELDS_CHANGED:" + ",".join(changed_strategy))

    receipt = {
        "version": VERSION,
        "target_session": target,
        "realtime_quote_available": realtime,
        "target_session_close": str(close) if close is not None else None,
        "raw_pipeline_sha256": _hash(pipeline_final),
        "release_view_sha256": _hash(release),
        "sanitized_paths": [row["path"] for row in changes],
        "sanitized_count": len(changes),
        "raw_sem001_codes": sorted({str(f.get("code")) for f in _semantic_001_findings(raw_audit)}),
        "release_sem001_codes": [],
        "strategy_fields_changed": False,
        "raw_pipeline_result_mutated": False,
        "model_requests": 0,
        "runtime_activated": False,
        "release_status": "PASS" if not remaining_sem001 else "BLOCK",
    }
    return {"release_result": release, "receipt": receipt, "release_audit": release_audit}
