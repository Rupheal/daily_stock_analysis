"""Deterministic post-output promotion contract for O-native evidence.

This layer never edits the preserved model result. It derives objective facts from
frozen inputs, applies the saved-output fact/semantic guards, and decides whether
that immutable result is eligible for downstream promotion. It never calls a
model, broker, market API, or search provider.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json

from o_single_output_fact_check import check_saved_output

CONTRACT_VERSION = 'O_POST_OUTPUT_CONTRACT_v1'


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def derive_open_gap(original_input):
    """Derive the only authoritative opening-gap direction from frozen prices."""
    ctx = original_input.get('context') or {}
    today = ctx.get('today') or {}
    yesterday = ctx.get('yesterday') or {}
    open_price = _number(today.get('open'))
    previous_close = _number(yesterday.get('close'))
    if open_price is None or previous_close is None:
        return {
            'status': 'UNVERIFIABLE',
            'direction': None,
            'open': str(open_price) if open_price is not None else None,
            'previous_close': str(previous_close) if previous_close is not None else None,
            'delta': None,
            'delta_pct': None,
        }
    delta = open_price - previous_close
    if delta > 0:
        direction = 'GAP_UP'
    elif delta < 0:
        direction = 'GAP_DOWN'
    else:
        direction = 'FLAT_OPEN'
    delta_pct = None if previous_close == 0 else (delta / previous_close)
    return {
        'status': 'PASS',
        'direction': direction,
        'open': str(open_price),
        'previous_close': str(previous_close),
        'delta': str(delta),
        'delta_pct': str(delta_pct) if delta_pct is not None else None,
    }


def validate_news_count_contract(result):
    """Enforce: known=true requires a non-negative integer count."""
    known = result.get('news_result_count_known')
    count = result.get('news_result_count')
    if known is True:
        valid = isinstance(count, int) and not isinstance(count, bool) and count >= 0
        return {
            'status': 'PASS' if valid else 'BLOCK',
            'known': True,
            'count': count,
            'required': 'non_negative_integer',
        }
    return {
        'status': 'PASS',
        'known': bool(known) if isinstance(known, bool) else known,
        'count': count,
        'required': 'non_negative_integer_only_when_known_true',
    }


def _stable_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def evaluate_post_output_contract(preflight, original_input, result):
    """Evaluate immutable Child/model output for promotion without rewriting it."""
    before = deepcopy((preflight, original_input, result))
    audit = check_saved_output(preflight, original_input, result)
    open_gap = derive_open_gap(original_input)
    news_count = validate_news_count_contract(result)

    block_findings = [f for f in audit['findings'] if f.get('severity') == 'BLOCK']
    sem_findings = [f for f in audit['findings'] if f.get('guard_id') in {'SEM-001', 'SEM-002', 'SEM-003'}]

    blockers = [f.get('code') for f in block_findings]
    blockers.extend(sorted({f.get('guard_id') for f in sem_findings if f.get('guard_id')}))
    if open_gap['status'] != 'PASS' and 'OPEN_GAP_UNVERIFIABLE' not in blockers:
        blockers.append('OPEN_GAP_UNVERIFIABLE')
    if news_count['status'] != 'PASS' and 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' not in blockers:
        blockers.append('NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER')

    promotion_allowed = not blockers
    result_snapshot = {
        'schema_version': 1,
        'contract_version': CONTRACT_VERSION,
        'guard_version': audit.get('guard_version'),
        'immutable_source_sha256': _stable_sha(result),
        'deterministic_facts': {
            'opening_gap': open_gap,
            'news_result_count': news_count,
        },
        'semantic_audit': audit,
        'formal_semantic_gates': {
            'SEM-001': 'BLOCK' if 'SEM-001' in audit.get('triggered_semantic_guards', []) else 'PASS',
            'SEM-002': 'BLOCK' if 'SEM-002' in audit.get('triggered_semantic_guards', []) else 'PASS',
            'SEM-003': 'BLOCK' if 'SEM-003' in audit.get('triggered_semantic_guards', []) else 'PASS',
        },
        'promotion_gate': {
            'status': 'PASS' if promotion_allowed else 'BLOCK',
            'blockers': blockers,
            'o_single_stock_formal_acceptance': promotion_allowed,
            'o_full_pool_permitted': False,
            'top3_permitted': False,
            'repeat_model_request_permitted': False,
        },
        'new_model_requests': 0,
        'source_result_mutated': False,
        'runtime_activated': False,
    }
    assert (preflight, original_input, result) == before, 'POST_OUTPUT_CONTRACT_MUTATED_PRESERVED_EVIDENCE'
    return result_snapshot
