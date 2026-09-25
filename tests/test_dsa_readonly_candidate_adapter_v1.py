import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dsa_readonly_candidate_adapter_v1 import compare_read_only, _fingerprint


TARGET = "2026-09-18"
NOW = "2026-09-19T20:19:00+08:00"
NEXT = "2026-09-21"
SEALED = "2026-09-19T20:18:00+08:00"
AVAILABLE = "2026-09-19T20:17:00+08:00"


def write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def o_wait():
    return {
        "status": "ACCEPTED_O_FORMAL_TOP3",
        "target_session": TARGET,
        "missing_count": 0,
        "qualified_buy_in_Top3": 0,
        "Top3": [
            {"code": "00148", "rank": 1, "sentiment_score": 59, "action": "hold", "action_family": "hold"},
            {"code": "00177", "rank": 2, "sentiment_score": 59, "action": "hold", "action_family": "hold"},
            {"code": "00552", "rank": 3, "sentiment_score": 59, "action": "hold", "action_family": "hold"},
        ],
    }


def u_blocked():
    return {
        "state": "PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
        "target_session": TARGET,
        "denominator": 45,
        "formal_valid_rows": 0,
        "qualified_BUY": 0,
        "Top3": [],
        "rows": [],
    }


def journal():
    cfg = "a" * 64
    h1 = "b" * 64
    return {
        "schema_version": 1,
        "config": {"real_orders_authorized": False},
        "config_hash": cfg,
        "commands": [
            {
                "parent": cfg,
                "command": {
                    "id": "existing-U-signal",
                    "account": "U",
                    "at": "2026-09-18T09:00:00+08:00",
                    "kind": "SIGNAL",
                    "signal": {"id": "U-old"},
                },
                "hash": h1,
            }
        ],
    }


def active_no_trade():
    return {
        "schema_version": "1.0.0",
        "session": TARGET,
        "runtime_activated": True,
        "shadow_simulation_only": True,
        "real_orders": 0,
        "fail_closed": True,
        "U": {"cash_cny": "300000", "positions": 0, "buy_count": 0, "sell_count": 0},
        "O": {"cash_cny": "300000", "positions": 0, "buy_count": 0, "sell_count": 0},
        "timeline": [],
    }


def make_inputs(tmp_path):
    op = write(tmp_path, "o.json", o_wait())
    up = write(tmp_path, "u.json", u_blocked())
    jp = write(tmp_path, "journal.json", journal())
    ap = write(tmp_path, "active.json", active_no_trade())
    return op, up, jp, ap


def natural_attestation(op, up, jp):
    return {
        "status": "PASS_SAME_CUTOFF_INPUTS",
        "target_session": TARGET,
        "next_session": NEXT,
        "cutoff_at": NOW,
        "sealed_at": SEALED,
        "input_available_at": {
            "o_receipt": AVAILABLE,
            "u_receipt": AVAILABLE,
            "foundation_journal": AVAILABLE,
        },
        "input_sha256": {
            "o_receipt": _fingerprint(op)["sha256"],
            "u_receipt": _fingerprint(up)["sha256"],
            "foundation_journal": _fingerprint(jp)["sha256"],
        },
    }


def test_read_only_adapter_never_mutates_foundation_journal(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    before = jp.read_bytes()
    result = compare_read_only(op, up, jp, ap, TARGET, NOW, NEXT)
    after = jp.read_bytes()

    assert before == after
    assert result["classification"] == "ENGINEERING_REPLAY_NOT_NATURAL_PARALLEL"
    assert result["read_only_contract"]["authoritative_journal_write_count"] == 0
    assert result["read_only_contract"]["candidate_journal_write_count"] == 0
    assert result["read_only_contract"]["foundation_journal_unchanged"] is True
    assert result["read_only_contract"]["real_orders"] == 0


def test_trade_action_equivalent_but_control_state_not_equivalent(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    result = compare_read_only(op, up, jp, ap, TARGET, NOW, NEXT)

    assert result["candidate"]["control_state"] == "BLOCKED"
    assert result["candidate"]["trade_action"] == "NO_TRADE"
    assert result["active"]["derived_control_state"] == "NO_TRADE_FAIL_CLOSED"
    assert result["comparison"]["trade_action_equivalent"] is True
    assert result["comparison"]["control_state_equivalent"] is False
    assert result["comparison"]["migration_acceptance"] == "NOT_ELIGIBLE_ENGINEERING_ONLY"


def test_engineering_replay_emits_comparison_only_and_no_entry(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    result = compare_read_only(op, up, jp, ap, TARGET, NOW, NEXT)

    assert result["candidate"]["entry_count"] == 0
    assert result["candidate"]["would_emit_command_count"] == 2
    assert result["candidate"]["would_append_command_count"] == 2
    assert all(x.startswith("signal-") for x in result["candidate"]["would_emit_command_ids"])


def test_natural_parallel_requires_hash_bound_attestation(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    with pytest.raises(ValueError, match="NATURAL_PARALLEL_ATTESTATION_REQUIRED"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
        )


def test_natural_parallel_rejects_wrong_input_hash(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    attestation = natural_attestation(op, up, jp)
    attestation["input_sha256"]["o_receipt"] = "0" * 64
    att = write(tmp_path, "attestation.json", attestation)

    with pytest.raises(ValueError, match="NATURAL_PARALLEL_INPUT_HASH_MISMATCH:o_receipt"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
            availability_attestation_path=att,
        )


def test_hash_bound_natural_parallel_can_reach_central_audit_eligibility(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    active = active_no_trade()
    active["session"] = NEXT
    ap.write_text(json.dumps(active), encoding="utf-8")
    attestation = natural_attestation(op, up, jp)
    att = write(tmp_path, "attestation.json", attestation)
    result = compare_read_only(
        op, up, jp, ap, TARGET, NOW, NEXT,
        comparison_kind="natural_parallel",
        availability_attestation_path=att,
    )

    assert result["classification"] == "NATURAL_PARALLEL_COMPARISON"
    assert result["natural_parallel_attestation"]["status"] == "PASS"
    assert "active_runtime_receipt" in result["outcome_evidence"]
    assert "active_runtime_receipt" not in result["prewindow_inputs"]
    assert result["comparison"]["trade_action_equivalent"] is True
    assert result["comparison"]["control_state_equivalent"] is False
    assert result["comparison"]["all_equivalent"] is False
    assert result["comparison"]["migration_acceptance"] == "CENTRAL_AUDIT_REQUIRED_CONTROL_STATE_DIVERGENCE"


def test_broken_foundation_parent_chain_fails_closed(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    bad = journal()
    bad["commands"][0]["parent"] = "c" * 64
    jp.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="FOUNDATION_JOURNAL_PARENT_CHAIN_INVALID"):
        compare_read_only(op, up, jp, ap, TARGET, NOW, NEXT)


def test_active_outcome_uses_window_actions_not_cumulative_positions(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    active = active_no_trade()
    active["O"]["positions"] = 1
    active["O"]["buy_count"] = 3
    active["timeline"] = [
        {"stage": "WINDOW_POINT", "account": "O", "status": "NO_TRADE"},
        {"stage": "EXPIRY", "account": "O", "status": "WINDOW_CLOSED"},
    ]
    ap.write_text(json.dumps(active), encoding="utf-8")
    result = compare_read_only(op, up, jp, ap, TARGET, NOW, NEXT)
    assert result["active"]["trade_action"] == "NO_TRADE"
    assert result["active"]["ending_positions"] == 1
    assert result["active"]["cumulative_buy_count"] == 3


def test_natural_parallel_rejects_wrong_outcome_session(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    attestation = natural_attestation(op, up, jp)
    att = write(tmp_path, "attestation.json", attestation)
    with pytest.raises(ValueError, match="NATURAL_PARALLEL_OUTCOME_SESSION_MISMATCH"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
            availability_attestation_path=att,
        )


def test_natural_parallel_rejects_attestation_sealed_after_cutoff(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    active = active_no_trade()
    active["session"] = NEXT
    ap.write_text(json.dumps(active), encoding="utf-8")
    attestation = natural_attestation(op, up, jp)
    attestation["sealed_at"] = "2026-09-19T20:20:00+08:00"
    att = write(tmp_path, "attestation.json", attestation)

    with pytest.raises(ValueError, match="NATURAL_PARALLEL_ATTESTATION_SEALED_AFTER_CUTOFF"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
            availability_attestation_path=att,
        )


def test_natural_parallel_rejects_input_available_after_seal(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    active = active_no_trade()
    active["session"] = NEXT
    ap.write_text(json.dumps(active), encoding="utf-8")
    attestation = natural_attestation(op, up, jp)
    attestation["input_available_at"]["u_receipt"] = "2026-09-19T20:18:30+08:00"
    att = write(tmp_path, "attestation.json", attestation)

    with pytest.raises(ValueError, match="NATURAL_PARALLEL_INPUT_AVAILABLE_AFTER_SEAL:u_receipt"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
            availability_attestation_path=att,
        )


def test_natural_parallel_rejects_naive_cutoff_timestamp(tmp_path):
    op, up, jp, ap = make_inputs(tmp_path)
    active = active_no_trade()
    active["session"] = NEXT
    ap.write_text(json.dumps(active), encoding="utf-8")
    attestation = natural_attestation(op, up, jp)
    attestation["cutoff_at"] = "2026-09-19T20:19:00"
    att = write(tmp_path, "attestation.json", attestation)

    with pytest.raises(ValueError, match="NATURAL_PARALLEL_CUTOFF_TIMEZONE_REQUIRED"):
        compare_read_only(
            op, up, jp, ap, TARGET, NOW, NEXT,
            comparison_kind="natural_parallel",
            availability_attestation_path=att,
        )
