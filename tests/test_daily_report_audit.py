import pytest
from datetime import date

from src.services.market_data_integrity import audit_daily_report, daily_consistency_facts, render_daily_consistency
from src.services.market_data_integrity import enforce_daily_report, withhold_unverified_hk_financials


def test_report_catches_observed_numeric_and_execution_conflicts():
    context = {'today':dict(open=25.66,high=26.66,low=25.44,close=26.36,volume_ratio=0.72), 'volume_change_ratio':0.76}
    result = {'pattern_analysis':'实体较小、上下影线均较长', 'dashboard':{
        'data_perspective':{'volume_analysis':{'volume_ratio':0.76}},
        'battle_plan':{'sniper_points':{'stop_loss':'25.00元'},
                       'position_strategy':{'risk_control':'回撤控制在5%以内'}}}}
    audit = audit_daily_report(result, context)
    assert not audit['passed']
    assert not audit['execution_plan_enabled']
    assert {x['code'] for x in audit['findings']} == {
        'volume_ratio_semantics','candle_body_claim','candle_shadow_claim','stop_distance_requires_entry_basis'}


def test_correctly_labeled_ratios_and_geometry_pass_selected_checks():
    context = {'today':dict(open=25.66,high=26.66,low=25.44,close=26.36,volume_ratio=0.72)}
    result = {'pattern_analysis':'阳线实体占全日振幅约57%', 'dashboard':{
        'data_perspective':{'volume_analysis':{'volume_ratio':0.72}}}}
    assert audit_daily_report(result,context)['passed']


def test_daily_geometry_and_both_volume_denominators_are_explicit():
    context = {'today': dict(date=date(2026, 9, 11), open=25.66, high=26.66, low=25.44, close=26.36, volume_ratio=0.72),
               'yesterday': {'close': 25.92}, 'volume_change_ratio': 0.76}
    facts = daily_consistency_facts(context)
    assert facts['candle_body'] == pytest.approx(0.70)
    assert facts['upper_shadow'] == pytest.approx(0.30)
    assert facts['lower_shadow'] == pytest.approx(0.22)
    assert facts['body_fraction_of_range'] == pytest.approx(0.70 / 1.22)
    assert facts['change_pct'] == pytest.approx(1.6975308642)
    assert facts['volume_vs_previous_five_sessions'] == 0.72
    assert facts['volume_vs_previous_session'] == 0.76
    assert facts['date'] == '2026-09-11'
    assert 'execution_basis' in render_daily_consistency(context)


def test_stop_risk_uses_explicit_entry_instead_of_last_close():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    result = {'dashboard': {'battle_plan': {
        'execution_basis': {'entry_price': 26.0, 'stop_price': 25.0, 'position_pct': 10},
        'sniper_points': {'stop_loss': '25.00元'},
        'position_strategy': {'risk_control': '股价止损距离控制在4%以内；跳空另计'},
    }}}
    assert audit_daily_report(result, context)['passed']
    result['dashboard']['battle_plan']['execution_basis']['entry_price'] = 27.0
    assert audit_daily_report(result, context)['findings'][0]['code'] == 'stop_distance_exceeds_claimed_cap'


def test_conflicting_stop_and_invalid_position_are_rejected():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    result = {'dashboard': {'battle_plan': {
        'execution_basis': {'entry_price': 26.0, 'stop_price': 25.0, 'position_pct': 150},
        'sniper_points': {'stop_loss': '24.00元'},
    }}}
    assert {x['code'] for x in audit_daily_report(result, context)['findings']} == {
        'conflicting_stop_prices', 'invalid_position_percentage'}


def test_account_risk_applies_position_weight_and_requires_its_basis():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    plan = {'execution_basis': {'entry_price': 26.0, 'stop_price': 25.0, 'position_pct': 10},
            'sniper_points': {'stop_loss': '25.00元'},
            'position_strategy': {'risk_control': '账户名义风险0.4%以内；不含跳空及费用'}}
    result = {'dashboard': {'battle_plan': plan}}
    assert audit_daily_report(result, context)['passed']
    plan['execution_basis']['position_pct'] = None
    assert audit_daily_report(result, context)['findings'][0]['code'] == 'account_risk_requires_entry_and_position'


def test_actual_report_cross_section_stop_and_primary_entry_conflicts_block():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    result = {'dashboard': {
        'core_conclusion': {'position_advice': {'has_position': '以25.44为止损线；跌破25.44无条件离场'}},
        'battle_plan': {
            'execution_basis': {'entry_price': 26.62, 'stop_price': 25.40, 'position_pct': 10},
            'sniper_points': {'ideal_buy': '理想买入点：26.60元附近（回踩MA5 26.62）',
                              'secondary_buy': '次优买入点：25.50元', 'stop_loss': '止损位：25.40元'},
            'position_strategy': {'risk_control': '以25.40为硬止损'},
        }}}
    codes = {x['code'] for x in audit_daily_report(result, context)['findings']}
    assert codes == {'cross_section_stop_conflict', 'primary_entry_conflict'}
    result['dashboard']['core_conclusion']['position_advice']['has_position'] = '以25.40为止损线'
    result['dashboard']['battle_plan']['sniper_points']['ideal_buy'] = '理想买入点：26.62元（MA5）'
    assert audit_daily_report(result, context)['passed']  # Secondary scenario is not the primary entry.


def test_unknown_regulatory_status_cannot_become_categorical_absence():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    bad = {'news_summary': '印度SFIO建议调查，尚未立案亦无裁决，属待核报道'}
    assert {x['code'] for x in audit_daily_report(bad, context)['findings']} == {'unverified_regulatory_absence'}
    good = {'news_summary': '建议调查，是否批准尚待决定；不能确认是否立案，当前状态未独立核实。'}
    assert audit_daily_report(good, context)['passed']


def test_unverified_financial_numbers_block_even_after_price_checks_pass():
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    bad = {'fundamental_analysis': '2026-06-30营业收入4381亿元、归母净利润330亿元、ROE12.63%'}
    assert audit_daily_report(bad, context)['findings'][0]['code'] == 'unverified_financial_claim'
    assert audit_daily_report({'fundamental_analysis': '财报期间、币种和单位待核验，无法判断'}, context)['passed']


def test_financial_withholding_preserves_raw_snapshot_and_other_markets():
    from copy import deepcopy
    raw = {'status': 'success', 'earnings': {'status': 'success', 'data': {'financial_report': {'revenue': 4381}}},
           'valuation': {'data': {'pe': 20}}, 'growth': {'data': {'revenue_yoy': 4}},
           'capital_flow': {'data': {'status': 'not_supported'}}, 'belong_boards': ['科技']}
    snapshot = deepcopy(raw)
    for market in ('cn', 'us'):
        assert withhold_unverified_hk_financials(raw, market) is raw
    cleaned = withhold_unverified_hk_financials(raw, 'hk')
    assert raw == snapshot
    for key in ('earnings', 'growth', 'valuation'):
        assert cleaned[key]['data'] == {}
        assert cleaned['coverage'][key] == 'failed'
    assert cleaned['capital_flow'] == raw['capital_flow']
    assert cleaned['belong_boards'] == ['科技']


def test_rejected_output_cannot_keep_executable_dashboard():
    from types import SimpleNamespace
    data = {'dashboard': {'battle_plan': {'execution_basis': {'entry_price': 26.62, 'stop_price': 25.40},
                                          'sniper_points': {'ideal_buy': '26.60元'}}}}
    obj = SimpleNamespace(**data, success=True, operation_advice='买入', decision_type='buy', action='buy',
                          action_label='买入', raw_response='original evidence', to_dict=lambda: data)
    audit = enforce_daily_report(obj, {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)})
    assert not audit['passed'] and not obj.success
    assert obj.dashboard is None and obj.action is None and obj.decision_type == 'hold'
    assert obj.raw_response == 'original evidence'


def test_replay_real_unapproved_model_output_without_another_model_call():
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/xiaomi_model_unapproved_20260912.json').read_text())
    audit = audit_daily_report(fixture['result'], fixture['context'])
    assert not audit['passed'] and not audit['execution_plan_enabled']
    assert {'cross_section_stop_conflict', 'primary_entry_conflict', 'unverified_financial_claim',
            'unverified_regulatory_absence'} <= {x['code'] for x in audit['findings']}
