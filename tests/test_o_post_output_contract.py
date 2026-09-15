from copy import deepcopy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from o_post_output_contract import derive_open_gap, evaluate_post_output_contract, validate_news_count_contract


def base_case():
    preflight = {'target': '2026-01-05', 'news_count': 0}
    original_input = {
        'context': {
            'date': '2026-01-05',
            'today': {'date': '2026-01-05', 'open': '10.0'},
            'yesterday': {'close': '10.2'},
        },
        'news_context': None,
    }
    result = {
        'pattern_analysis': '低开，开盘低于前收',
        'action': 'watch',
        'news_result_count_known': False,
        'news_result_count': None,
        'current_price': None,
        'search_performed': False,
    }
    return preflight, original_input, result


def test_open_gap_is_derived_from_frozen_prices():
    _, i, _ = base_case()
    gap = derive_open_gap(i)
    assert gap['status'] == 'PASS'
    assert gap['direction'] == 'GAP_DOWN'
    assert gap['open'] == '10.0'
    assert gap['previous_close'] == '10.2'


def test_open_gap_up_and_flat_are_deterministic():
    _, i, _ = base_case()
    i['context']['today']['open'] = '10.3'
    assert derive_open_gap(i)['direction'] == 'GAP_UP'
    i['context']['today']['open'] = '10.2'
    assert derive_open_gap(i)['direction'] == 'FLAT_OPEN'


def test_open_gap_nonfinite_is_unverifiable():
    _, i, _ = base_case()
    i['context']['today']['open'] = 'NaN'
    assert derive_open_gap(i)['status'] == 'UNVERIFIABLE'


def test_known_news_count_requires_nonnegative_integer():
    _, _, r = base_case()
    for bad in (None, True, -1, 1.5, '2'):
        r2 = deepcopy(r)
        r2.update(news_result_count_known=True, news_result_count=bad)
        assert validate_news_count_contract(r2)['status'] == 'BLOCK'
    r.update(news_result_count_known=True, news_result_count=0)
    assert validate_news_count_contract(r)['status'] == 'PASS'
    r['news_result_count'] = 3
    assert validate_news_count_contract(r)['status'] == 'PASS'


def test_unknown_news_count_does_not_require_integer():
    _, _, r = base_case()
    r.update(news_result_count_known=False, news_result_count=None)
    assert validate_news_count_contract(r)['status'] == 'PASS'


def test_clean_output_passes_promotion_gate():
    p, i, r = base_case()
    out = evaluate_post_output_contract(p, i, r)
    assert out['deterministic_facts']['opening_gap']['direction'] == 'GAP_DOWN'
    assert out['formal_semantic_gates'] == {'SEM-001': 'PASS', 'SEM-002': 'PASS', 'SEM-003': 'PASS'}
    assert out['promotion_gate']['status'] == 'PASS'
    assert out['promotion_gate']['o_single_stock_formal_acceptance'] is True
    assert out['new_model_requests'] == 0


def test_open_direction_contradiction_blocks_promotion():
    p, i, r = base_case()
    r['pattern_analysis'] = '高开，开盘高于前收'
    out = evaluate_post_output_contract(p, i, r)
    assert out['deterministic_facts']['opening_gap']['direction'] == 'GAP_DOWN'
    assert 'OPEN_GAP_DIRECTION_CONTRADICTION' in out['promotion_gate']['blockers']
    assert out['promotion_gate']['status'] == 'BLOCK'


def test_invalid_known_news_count_blocks_promotion():
    p, i, r = base_case()
    r.update(news_result_count_known=True, news_result_count=None)
    out = evaluate_post_output_contract(p, i, r)
    assert out['deterministic_facts']['news_result_count']['status'] == 'BLOCK'
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' in out['promotion_gate']['blockers']


def test_sem001_is_formal_promotion_gate():
    p, i, r = base_case()
    r['dashboard'] = {'data_perspective': {'price_position': {'current_price': 10.1}}}
    out = evaluate_post_output_contract(p, i, r)
    assert out['formal_semantic_gates']['SEM-001'] == 'BLOCK'
    assert 'SEM-001' in out['promotion_gate']['blockers']


def test_sem002_is_formal_promotion_gate():
    p, i, r = base_case()
    r['checklist'] = '未见近3日利空公告'
    out = evaluate_post_output_contract(p, i, r)
    assert out['formal_semantic_gates']['SEM-002'] == 'BLOCK'
    assert 'SEM-002' in out['promotion_gate']['blockers']


def test_sem003_is_formal_promotion_gate():
    p, i, r = base_case()
    r['sector_position'] = '公司是恒生科技指数权重股之一'
    out = evaluate_post_output_contract(p, i, r)
    assert out['formal_semantic_gates']['SEM-003'] == 'BLOCK'
    assert 'SEM-003' in out['promotion_gate']['blockers']


def test_contract_does_not_mutate_saved_evidence():
    p, i, r = base_case()
    r.update(pattern_analysis='高开', checklist='未见利空公告', sector_position='恒生科技指数权重股之一')
    before = deepcopy((p, i, r))
    a = evaluate_post_output_contract(p, i, r)
    b = evaluate_post_output_contract(p, i, r)
    assert a == b
    assert (p, i, r) == before
    assert a['source_result_mutated'] is False
    assert a['promotion_gate']['repeat_model_request_permitted'] is False
