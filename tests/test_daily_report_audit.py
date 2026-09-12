import pytest
from datetime import date

from src.services.market_data_integrity import audit_daily_report, daily_consistency_facts, render_daily_consistency


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
