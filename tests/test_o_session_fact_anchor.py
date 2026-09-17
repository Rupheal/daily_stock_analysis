from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from o_session_fact_anchor import (
    SessionFactError, build_session_fact_anchor_from_preflight, prove_session_fact_anchor,
)
from o_semantic_handoff_contract import (
    CONTRACT_VERSION as HANDOFF_VERSION, FROZEN_UPSTREAM, canonical_hash,
    build_news_handoff,
)
from o_post_output_contract import build_final_capture, evaluate_post_output_contract
from o_capture_stage_provenance import PINNED_SHA256


def preflight():
    return {
        'passed': True, 'prices_passed': True, 'symbol': 'HK01810', 'target': '2026-09-15',
        'prepared_at': '2026-09-16T01:00:00+00:00',
        'component_status': {'news': 'passed_limited_coverage'},
        'execution_contract': {
            'version': 'O_GATE_A_EXECUTION_CONTRACT_v2', 'target_session': '2026-09-15',
            'realtime_quote_available': False, 'session_fact_anchor_required': True,
        },
        'today': {'date': '2026-09-15', 'open': 27.12, 'close': 26.50},
        'yesterday': {'date': '2026-09-14', 'close': 27.16},
        'news_count': 1, 'allowed_news_urls': ['https://example.org/e1'],
        'company_news_evidence': [{
            'event_id': 'e1', 'title': '合成新闻', 'summary': '仅合成测试，不是市场事实',
            'source': 'fixture', 'published_at': '2026-09-15T08:00:00+00:00',
            'source_urls': ['https://example.org/e1'],
            'source_records': [{'source': 'fixture', 'url': 'https://example.org/e1'}],
            'evidence_kind': '摘要，非全文',
        }],
    }


def live_context():
    return {
        'code': 'HK01810', 'date': date(2026, 9, 15), 'news_window_days': 3,
        'today': {'date': date(2026, 9, 15), 'open': 27.1200008392334, 'close': 26.5},
        'yesterday': {'date': date(2026, 9, 14), 'close': 27.15999984741211},
    }


def source():
    return {
        'frozen_upstream': FROZEN_UPSTREAM,
        'pipeline_sha256': PINNED_SHA256['pipeline'],
        'observer_sha256': 'a' * 64,
        'pipeline_module_under_checkout': True,
    }


def clean_result():
    return {
        'success':True,'error_message':None,
        'pattern_analysis': '9月15日小幅低开后冲高回落；这里只描述目标交易日，不声称实时行情。',
        'analysis_summary': '基于9月15日完整日线收盘价26.50元；实时行情缺失。',
        'action': 'watch', 'current_price': None, 'search_performed': False,
        'news_result_count_known': True, 'news_result_count': None,
    }


def test_anchor_facts_are_explicit_and_price_wording_rule_is_bound():
    a = build_session_fact_anchor_from_preflight(preflight())
    assert a['facts']['opening_direction'] == 'DOWN'
    assert a['facts']['opening_label_zh'] == '低开'
    assert a['facts']['previous_close'] == '27.16'
    assert a['facts']['target_session_close'] == '26.5'
    assert a['facts']['realtime_quote_available'] is False
    assert '不得称现价' in a['text']


def test_anchor_requires_explicit_execution_contract():
    p = preflight(); p.pop('execution_contract')
    with pytest.raises(SessionFactError, match='EXECUTION_CONTRACT'):
        build_session_fact_anchor_from_preflight(p)


def test_anchor_prompt_proof_requires_exactly_once():
    a = build_session_fact_anchor_from_preflight(preflight())
    assert prove_session_fact_anchor('header\n' + a['text'], a)['consumed_exactly_once']
    for prompt in ('none', a['text'] + a['text']):
        with pytest.raises(SessionFactError):
            prove_session_fact_anchor(prompt, a)


def test_date_object_live_context_and_string_snapshot_bind_same_v2_handoff():
    p = preflight(); live = live_context()
    h = build_news_handoff(p, live, expected_preflight_hash=canonical_hash(p),
                           decision_at='2026-09-16T01:01:00+00:00')
    snapshot_context = json.loads(json.dumps(live, default=str))
    snapshot = {'context': snapshot_context, 'news_context': h['news_context'],
                'analysis_context_pack_summary': 'synthetic', 'capture_stage': 'ANALYZER_ENTRY'}
    r = clean_result(); analyzer = deepcopy(r)
    cap = build_final_capture(p, snapshot, analyzer, r, source_proof=source(), input_version=HANDOFF_VERSION)
    out = evaluate_post_output_contract(
        p, snapshot, r, capture_receipt=cap, analyzer_result=analyzer,
        expected_sources=source(), prompt_text='header\n' + h['news_context'],
        news_handoff=h, required_handoff=True,
    )
    assert out['evidence_handoff']['status'] == 'PASS'
    assert out['session_fact_handoff']['status'] == 'PASS'
    assert out['semantic_contract_pass'] is True
    assert out['promotion_gate']['status'] == 'PASS'


def test_tampered_anchor_or_context_identity_still_blocks():
    p = preflight(); live = live_context()
    h = build_news_handoff(p, live, expected_preflight_hash=canonical_hash(p),
                           decision_at='2026-09-16T01:01:00+00:00')
    snap = {'context': json.loads(json.dumps(live, default=str)), 'news_context': h['news_context']}
    r = clean_result(); cap = build_final_capture(p, snap, r, r, source_proof=source(), input_version=HANDOFF_VERSION)
    bad = deepcopy(h); bad['session_fact_anchor']['facts']['opening_direction'] = 'UP'
    out = evaluate_post_output_contract(p, snap, r, capture_receipt=cap, analyzer_result=r,
        expected_sources=source(), prompt_text='header\n' + h['news_context'], news_handoff=bad, required_handoff=True)
    assert out['promotion_gate']['status'] == 'BLOCK'
    assert any('NEWS_HANDOFF_UNPROVEN' in x for x in out['promotion_gate']['blockers'])
