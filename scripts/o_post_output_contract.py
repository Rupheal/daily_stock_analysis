"""Versioned offline contract; no native-field mutation or model authorization.

v2 uses frozen native tri-state semantics, binds PIPELINE_FINALIZED provenance,
and keeps semantic eligibility separate from formal O acceptance. Historical
analyzer-return snapshots can be audited but cannot establish final metadata.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import re

from o_single_output_fact_check import check_saved_output
from o_semantic_handoff_contract import (
    FROZEN_UPSTREAM, ContractError, canonical_hash, news_count_state,
    opening_check, prove_prompt_consumption, build_news_handoff, CONTRACT_VERSION as HANDOFF_VERSION,
)
from o_capture_stage_provenance import PINNED_SHA256

CONTRACT_VERSION = 'O_POST_OUTPUT_CONTRACT_v2'
CAPTURE_VERSION = 'O_PIPELINE_FINAL_CAPTURE_v1'
NUMERIC_COUNT_VERSION = 'O_NUMERIC_SEARCH_COUNT_v1'
FINAL_STAGE = 'PIPELINE_FINALIZED_AFTER_ANALYZE_STOCK_RETURN'
EARLY_STAGE = 'ANALYZER_RETURN_BEFORE_PIPELINE_ANNOTATION'
SEM_GATES = frozenset({'SEM-001', 'SEM-002', 'SEM-003'})


def derive_open_gap(original_input):
    """Reuse shared Decimal arithmetic rather than a second numeric rule."""
    facts = opening_check(original_input, {})['facts']
    if facts is None:
        return {'status': 'UNVERIFIABLE', 'direction': None}
    return {'status': 'PASS', 'direction': {
        'UP': 'GAP_UP', 'DOWN': 'GAP_DOWN', 'FLAT': 'FLAT_OPEN'
    }[facts['direction']], 'open': facts['open'],
        'previous_close': facts['previous_close'], 'delta': facts['difference'],
        'gap_percent': facts['gap_pct'], 'source': 'shared opening_check'}


def validate_news_count_contract(result, *, final_stage_verified=False):
    """Raw tri-state is not a numeric known flag; stages never auto-promote."""
    state = news_count_state(result)
    return {'status': 'BLOCK' if state['findings'] else 'PASS',
            'native_state': state,
            'final_search_state': state['state'] if final_stage_verified else 'UNKNOWN_AT_CAPTURE_STAGE',
            'numeric_count_known': bool(final_stage_verified and state['numeric_count_known']),
            'numeric_count': state['count'] if final_stage_verified else None,
            'final_stage_verified': final_stage_verified,
            'supplied_evidence_count_is_search_hits': False}


def validate_numeric_count_sidecar(sidecar):
    """Only this separately named interface requires a known numeric count."""
    if sidecar is None:
        return {'status': 'NOT_SUPPLIED', 'numeric_count_known': False, 'numeric_count': None}
    if not isinstance(sidecar, dict):
        return {'status': 'BLOCK', 'code': 'NUMERIC_COUNT_SIDECAR_NOT_MAPPING'}
    known, count = sidecar.get('numeric_count_known'), sidecar.get('numeric_count')
    ok = (sidecar.get('version') == NUMERIC_COUNT_VERSION and type(known) is bool
          and ((known and type(count) is int and count >= 0) or (not known and count is None)))
    return {'status': 'PASS' if ok else 'BLOCK',
            'code': None if ok else 'NUMERIC_COUNT_SIDECAR_INVALID',
            'numeric_count_known': known, 'numeric_count': count}


def build_final_capture(preflight, original_input, analyzer_result, final_result, *, source_proof, input_version):
    """Called only after actual analyze_stock returns; hashes are not signatures.

    Trust comes from the audited external hook + pinned native source, not from
    the self-reported stage label alone. Validator binds all captured objects.
    """
    return {'version': CAPTURE_VERSION, 'stage': FINAL_STAGE,
            'hook': 'StockAnalysisPipeline.analyze_stock:AFTER_NORMAL_RETURN',
            'pipeline_returned': True, 'input_version': input_version,
            'symbol': str(preflight.get('symbol', '')).upper(),
            'target_session': preflight.get('target'),
            'preflight_sha256': canonical_hash(preflight),
            'input_sha256': canonical_hash(original_input),
            'analyzer_result_sha256': canonical_hash(analyzer_result),
            'final_result_sha256': canonical_hash(final_result),
            'source_proof': deepcopy(source_proof)}


def _capture_checks(preflight, original_input, result, receipt, analyzer_result, expected_sources):
    if not isinstance(receipt, dict) or receipt.get('stage') != FINAL_STAGE:
        return ['FINAL_CAPTURE_MISSING_OR_WRONG_STAGE']
    failures = []
    if (receipt.get('version') != CAPTURE_VERSION or receipt.get('pipeline_returned') is not True
            or receipt.get('hook') != 'StockAnalysisPipeline.analyze_stock:AFTER_NORMAL_RETURN'):
        failures.append('FINAL_CAPTURE_CONTRACT_INVALID')
    if receipt.get('input_version') not in (HANDOFF_VERSION, 'FROZEN_NATIVE_INPUT_NO_HANDOFF_v1'):
        failures.append('INPUT_VERSION_MISSING')
    ctx = original_input.get('context') or {}
    if (not preflight.get('symbol') or str(preflight['symbol']).upper() != str(ctx.get('code', '')).upper()
            or receipt.get('symbol') != str(preflight.get('symbol', '')).upper()
            or receipt.get('target_session') != preflight.get('target')):
        failures.append('FINAL_CAPTURE_IDENTITY_MISMATCH')
    expected = expected_sources or {}
    if (receipt.get('source_proof') != expected
            or expected.get('frozen_upstream') != FROZEN_UPSTREAM
            or expected.get('pipeline_sha256') != PINNED_SHA256['pipeline']
            or expected.get('pipeline_module_under_checkout') is not True
            or not re.fullmatch(r'[a-f0-9]{64}', str(expected.get('observer_sha256', '')))):
        failures.append('FINAL_CAPTURE_SOURCE_UNPROVEN')
    for field, value in [('preflight', preflight), ('input', original_input),
                         ('analyzer_result', analyzer_result), ('final_result', result)]:
        if not isinstance(value, dict) or receipt.get(field + '_sha256') != canonical_hash(value):
            failures.append('FINAL_CAPTURE_HASH_MISMATCH:' + field)
    return failures


def evaluate_post_output_contract(preflight, original_input, result, *, capture_receipt=None,
                                  analyzer_result=None, expected_sources=None, prompt_text=None,
                                  news_handoff=None, numeric_sidecar=None, required_handoff=False):
    """One output decision for offline audit and the actual wrapper exit.

    Missing final provenance is a BLOCK, not an invitation to create a final
    historic snapshot. Passing this narrow gate never grants model or trade use.
    """
    before = deepcopy((preflight, original_input, result))
    audit = check_saved_output(preflight, original_input, result)
    capture_blocks = _capture_checks(preflight, original_input, result, capture_receipt,
                                     analyzer_result, expected_sources)
    count = validate_news_count_contract(result, final_stage_verified=not capture_blocks)
    numeric = validate_numeric_count_sidecar(numeric_sidecar)
    blockers = [f['code'] for f in audit['findings'] if f.get('severity') == 'BLOCK']
    blockers += sorted({f['guard_id'] for f in audit['findings'] if f.get('guard_id') in SEM_GATES})
    blockers += capture_blocks
    # A preflight list is not proof that native prompt consumed that evidence.
    blockers += [f['code'] for f in audit['findings'] if f.get('severity') == 'INTEGRATION_GAP']
    if numeric['status'] == 'BLOCK':
        blockers.append(numeric['code'])
    if numeric['status'] == 'PASS' and (not count['final_stage_verified'] or
            numeric['numeric_count_known'] != count['numeric_count_known'] or
            numeric['numeric_count'] != count['numeric_count']):
        blockers.append('NUMERIC_COUNT_SIDECAR_STATE_MISMATCH')
    count_in_preflight = preflight.get('news_count')
    handoff_required = bool(required_handoff or (type(count_in_preflight) is int and count_in_preflight > 0))
    expected_input_version = HANDOFF_VERSION if (handoff_required or news_handoff is not None) else 'FROZEN_NATIVE_INPUT_NO_HANDOFF_v1'
    if isinstance(capture_receipt, dict) and capture_receipt.get('stage') == FINAL_STAGE and capture_receipt.get('input_version') != expected_input_version:
        blockers.append('INPUT_VERSION_BINDING_MISMATCH')
    handoff = {'required': handoff_required, 'status': 'NOT_REQUESTED',
               'supplied_evidence_count': None, 'not_search_hit_count': True}
    if handoff_required or news_handoff is not None:
        try:
            if not isinstance(news_handoff, dict) or not isinstance(prompt_text, str):
                raise ContractError('NEWS_HANDOFF_OR_CAPTURED_PROMPT_MISSING')
            if (original_input.get('news_context') != news_handoff.get('news_context')
                    or news_handoff.get('preflight_hash') != canonical_hash(preflight)
                    or news_handoff.get('native_context_hash') != canonical_hash(original_input.get('context'))
                    or news_handoff.get('symbol') != str(preflight.get('symbol','')).upper()
                    or news_handoff.get('target_session') != preflight.get('target')
                    or sha256(news_handoff.get('news_context','').encode()).hexdigest() != news_handoff.get('news_context_sha256')):
                raise ContractError('NEWS_HANDOFF_INPUT_BINDING_MISMATCH')
            rebuilt = build_news_handoff(preflight, original_input['context'],
                expected_preflight_hash=canonical_hash(preflight), decision_at=news_handoff.get('decision_at'))
            if canonical_hash(rebuilt) != canonical_hash(news_handoff):
                raise ContractError('NEWS_HANDOFF_MANIFEST_CHANGED')
            proof = prove_prompt_consumption(prompt_text, news_handoff)
            handoff.update(status='PASS', supplied_evidence_count=news_handoff['admitted_evidence_count'], proof=proof)
        except (ContractError, KeyError, TypeError) as exc:
            blockers.append('NEWS_HANDOFF_UNPROVEN:' + str(exc))
            handoff['status'] = 'BLOCK'
    blockers = list(dict.fromkeys(blockers))
    allowed = not blockers
    output = {'schema_version': 2, 'contract_version': CONTRACT_VERSION,
              'guard_version': audit['guard_version'], 'immutable_source_sha256': canonical_hash(result),
              'deterministic_facts': {'opening_gap': derive_open_gap(original_input), 'news_result_count': count},
              'numeric_count_sidecar': numeric, 'evidence_handoff': handoff,
              'capture_stage': capture_receipt.get('stage') if isinstance(capture_receipt, dict) else 'UNPROVEN',
              'capture_verified': not capture_blocks,
              'semantic_audit': audit,
              'formal_semantic_gates': {g: ('BLOCK' if g in blockers else 'PASS') for g in sorted(SEM_GATES)},
              'semantic_contract_pass': allowed,
              'promotion_gate': {'status': 'PASS' if allowed else 'BLOCK', 'blockers': blockers,
                                 'o_single_stock_formal_acceptance': False, 'o_full_pool_permitted': False,
                                 'top3_permitted': False, 'repeat_model_request_permitted': False},
              'remaining_acceptance': ['input/request/storage provenance', 'manual scoped review', 'applicable authorization'],
              'new_model_requests': 0, 'source_result_mutated': False, 'runtime_activated': False}
    assert (preflight, original_input, result) == before, 'PRESERVED_EVIDENCE_MUTATED'
    return output


def output_exit_code(contract, *, request_count, error=None, native_status=None):
    """Fail closed on the formal gate, including SEM-only and missing-stage cases."""
    return 0 if (type(request_count) is int and request_count == 1 and not error
                 and native_status in (None, 0)
                 and isinstance(contract, dict) and contract.get('contract_version') == CONTRACT_VERSION
                 and contract.get('semantic_contract_pass') is True
                 and contract.get('promotion_gate', {}).get('status') == 'PASS') else 1
