from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from o_release_quote_semantics import ReleaseQuoteError, build_release_view


def fixture(realtime=False):
    preflight = {
        'target': '2026-09-15', 'news_count': 0,
        'today': {'date': '2026-09-15', 'close': 26.5},
        'execution_contract': {
            'version': 'O_GATE_A_EXECUTION_CONTRACT_v2',
            'target_session': '2026-09-15',
            'realtime_quote_available': realtime,
            'session_fact_anchor_required': True,
        },
    }
    original_input = {
        'context': {
            'date': '2026-09-15',
            'today': {'date': '2026-09-15', 'open': 27.12, 'close': 26.5},
            'yesterday': {'date': '2026-09-14', 'close': 27.16},
        },
        'news_context': None,
    }
    result = {
        'pattern_analysis': '9月15日低开后整理',
        'analysis_summary': '实时行情缺失，仅使用目标交易日收盘价26.50元。',
        'action': 'watch', 'operation_advice': '观望', 'decision_type': 'hold',
        'sentiment_score': 45, 'current_price': None,
        'search_performed': False,
        'news_result_count_known': False, 'news_result_count': None,
        'dashboard': {
            'data_perspective': {'price_position': {'current_price': 26.5, 'ma5': 26.46}},
            'decision_stability': {'applied': False, 'current_price': 26.5,
                                   'support': 26.46, 'resistance': 27.07},
        },
    }
    return preflight, original_input, result


def test_run031_shape_nulls_only_proven_completed_close_current_price_fields():
    p, i, raw = fixture(False); before = deepcopy(raw)
    out = build_release_view(p, i, raw)
    release = out['release_result']; receipt = out['receipt']
    assert raw == before
    assert release['current_price'] is None
    assert release['dashboard']['data_perspective']['price_position']['current_price'] is None
    assert release['dashboard']['decision_stability']['current_price'] is None
    assert release['dashboard']['data_perspective']['price_position']['ma5'] == 26.46
    assert release['dashboard']['decision_stability']['support'] == 26.46
    assert release['action'] == raw['action'] and release['sentiment_score'] == raw['sentiment_score']
    assert receipt['sanitized_count'] == 2
    assert sorted(receipt['sanitized_paths']) == sorted([
        '$.dashboard.data_perspective.price_position.current_price',
        '$.dashboard.decision_stability.current_price',
    ])
    assert receipt['strategy_fields_changed'] is False
    assert receipt['raw_pipeline_result_mutated'] is False
    assert receipt['release_status'] == 'PASS'
    assert receipt['release_sem001_codes'] == []


def test_different_numeric_current_price_fails_closed_instead_of_rewriting():
    p, i, raw = fixture(False)
    raw['dashboard']['decision_stability']['current_price'] = 26.6
    with pytest.raises(ReleaseQuoteError, match='NONREALTIME_CURRENT_PRICE_NOT_TARGET_CLOSE'):
        build_release_view(p, i, raw)


def test_native_error_default_never_becomes_release_success():
    p,i,raw=fixture(False);raw.update(success=False,error_message='synthetic model timeout',sentiment_score=50)
    with pytest.raises(ReleaseQuoteError,match='RELEASE_NATIVE_ANALYSIS_FAILED'):
        build_release_view(p,i,raw)


def test_unsafe_live_price_text_remains_a_blocker_and_is_never_rewritten():
    p, i, raw = fixture(False)
    raw['analysis_summary'] = '现价26.50元，建议观望'
    before = raw['analysis_summary']
    with pytest.raises(ReleaseQuoteError, match='RELEASE_SEM001_REMAINS'):
        build_release_view(p, i, raw)
    assert raw['analysis_summary'] == before


def test_realtime_true_does_not_sanitize_numeric_current_price_fields():
    p, i, raw = fixture(True)
    raw['current_price'] = 26.6
    raw['dashboard']['data_perspective']['price_position']['current_price'] = 26.6
    raw['dashboard']['decision_stability']['current_price'] = 26.6
    out = build_release_view(p, i, raw)
    assert out['receipt']['sanitized_count'] == 0
    assert out['release_result'] == raw


def test_missing_or_malformed_execution_contract_fails_closed():
    p, i, raw = fixture(False)
    p.pop('execution_contract')
    with pytest.raises(ReleaseQuoteError, match='EXECUTION_CONTRACT'):
        build_release_view(p, i, raw)
    p, i, raw = fixture(False)
    p['execution_contract']['realtime_quote_available'] = 'false'
    with pytest.raises(ReleaseQuoteError, match='REALTIME_AVAILABILITY'):
        build_release_view(p, i, raw)


def test_target_close_must_be_proven_positive_numeric():
    p, i, raw = fixture(False)
    p['today']['close'] = None
    with pytest.raises(ReleaseQuoteError, match='TARGET_CLOSE_UNPROVEN'):
        build_release_view(p, i, raw)


def test_nested_future_current_price_key_is_caught_deterministically():
    p, i, raw = fixture(False)
    raw['future_extension'] = {'deep': [{'current_price': 26.5}]}
    out = build_release_view(p, i, raw)
    assert out['release_result']['future_extension']['deep'][0]['current_price'] is None
    assert '$.future_extension.deep[0].current_price' in out['receipt']['sanitized_paths']


def test_raw_and_release_hashes_differ_only_when_sanitization_occurs():
    p, i, raw = fixture(False)
    out = build_release_view(p, i, raw)
    assert out['receipt']['raw_pipeline_sha256'] != out['receipt']['release_view_sha256']
    p, i, raw = fixture(True)
    out = build_release_view(p, i, raw)
    assert out['receipt']['raw_pipeline_sha256'] == out['receipt']['release_view_sha256']
