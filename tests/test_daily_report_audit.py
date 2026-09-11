from src.services.market_data_integrity import audit_daily_report


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
