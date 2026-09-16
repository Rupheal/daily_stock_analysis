from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from o_release_gate_contract import ReleaseGateError, evaluate_release_gate


def raw_contract(blockers=None, sem001_codes=None):
    blockers = ['SEM-001'] if blockers is None else blockers
    sem001_codes = ['SEM001_LIVE_PRICE_FIELD_WITHOUT_REALTIME_QUOTE'] if sem001_codes is None else sem001_codes
    return {
        'capture_verified': True,
        'evidence_handoff': {'status': 'PASS'},
        'session_fact_handoff': {'status': 'PASS'},
        'promotion_gate': {'status': 'BLOCK', 'blockers': blockers},
        'formal_semantic_gates': {'SEM-001': 'BLOCK', 'SEM-002': 'PASS', 'SEM-003': 'PASS'},
        'semantic_audit': {'findings': [
            {'code': code, 'guard_id': 'SEM-001', 'severity': 'CONDITION'} for code in sem001_codes
        ]},
    }


def release_bundle():
    return {
        'receipt': {
            'version': 'O_RELEASE_QUOTE_SEMANTICS_v1', 'release_status': 'PASS',
            'raw_pipeline_result_mutated': False, 'strategy_fields_changed': False,
            'sanitized_paths': ['$.dashboard.data_perspective.price_position.current_price'],
            'release_sem001_codes': [],
        },
        'release_audit': {'triggered_semantic_guards': []},
    }


def test_exact_run031_class_is_successor_candidate_but_raw_pass_remains_false():
    out = evaluate_release_gate(raw_contract(), release_bundle())
    assert out['status'] == 'PASS_WITH_VERSIONED_RELEASE_ADAPTER'
    assert out['raw_native_pipeline_semantic_pass'] is False
    assert out['raw_native_pipeline_preserved'] is True
    assert out['release_view_semantic_pass'] is True
    assert out['gate_a_successor_candidate'] is True
    assert out['gate_b_permitted'] is False and out['o_full_pool_permitted'] is False


def test_any_non_sem001_raw_blocker_fails_closed():
    with pytest.raises(ReleaseGateError, match='RAW_BLOCKER_NOT_RELEASE_SANITIZABLE'):
        evaluate_release_gate(raw_contract(['SEM-001','OPEN_GAP_DIRECTION_CONTRADICTION']), release_bundle())


def test_unsafe_text_sem001_is_not_release_sanitizable():
    with pytest.raises(ReleaseGateError, match='RAW_SEM001_CODE_NOT_RELEASE_SANITIZABLE'):
        evaluate_release_gate(raw_contract(sem001_codes=['SEM001_LIVE_PRICE_LABEL_WITHOUT_REALTIME_QUOTE']), release_bundle())


def test_sem002_or_sem003_raw_failure_cannot_be_hidden():
    raw = raw_contract(); raw['formal_semantic_gates']['SEM-002'] = 'BLOCK'
    with pytest.raises(ReleaseGateError, match='RAW_OTHER_SEMANTIC_GATE_NOT_PASSED'):
        evaluate_release_gate(raw, release_bundle())


def test_release_view_must_clear_all_semantic_guards():
    b = release_bundle(); b['release_audit']['triggered_semantic_guards'] = ['SEM-001']
    with pytest.raises(ReleaseGateError, match='RELEASE_VIEW_SEMANTIC_GATE_REMAINS'):
        evaluate_release_gate(raw_contract(), b)


def test_no_proven_release_change_cannot_upgrade_raw_failure():
    b = release_bundle(); b['receipt']['sanitized_paths'] = []
    with pytest.raises(ReleaseGateError, match='DID_NOT_MAKE_A_PROVEN_CHANGE'):
        evaluate_release_gate(raw_contract(), b)


def test_capture_and_handoffs_remain_mandatory():
    for field, message in [
        ('capture_verified','RAW_FINAL_CAPTURE_NOT_VERIFIED'),
        ('evidence_handoff','RAW_EVIDENCE_HANDOFF_NOT_PASSED'),
        ('session_fact_handoff','RAW_SESSION_FACT_HANDOFF_NOT_PASSED'),
    ]:
        raw = raw_contract()
        if field == 'capture_verified': raw[field] = False
        else: raw[field]['status'] = 'BLOCK'
        with pytest.raises(ReleaseGateError, match=message):
            evaluate_release_gate(raw, release_bundle())


def test_adapter_invariants_are_mandatory():
    b = release_bundle(); b['receipt']['strategy_fields_changed'] = True
    with pytest.raises(ReleaseGateError, match='INVARIANT_FAILED'):
        evaluate_release_gate(raw_contract(), b)
