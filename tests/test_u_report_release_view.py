from copy import deepcopy
import pytest
from test_u_member_reports import sample
from u_report_release_view import build_release


def test_release_labels_prior_close_without_changing_decision_or_raw():
    source,raw=sample();raw['thesis']='短期均线高于现价，趋势仍需进一步确认。';before=deepcopy(raw)
    view,receipt=build_release(raw,source)
    assert '所列数据日收盘价' in view['thesis'] and view['decision']==raw['decision']
    assert raw==before and receipt['raw_preserved'] and not receipt['formal_BUY_accepted']


def test_positive_histogram_not_claimed_as_new_crossover():
    source,raw=sample();source=deepcopy(source);source['facts']['macd']={'histogram_2x':1}
    raw['thesis']='动能柱转正，但中期方向仍需继续观察。'
    view,r=build_release(raw,source);assert '动能柱为正' in view['thesis']
    source['facts']['macd']['histogram_2x']=-1
    with pytest.raises(ValueError):build_release(raw,source)


def test_oversold_error_repair_is_only_for_proven_weak_not_oversold_range():
    source,raw=sample();source=deepcopy(source);source['facts']['rsi14']=35
    raw['thesis']='短线存在超卖修复可能，方向仍待进一步确认。'
    view,r=build_release(raw,source);assert '弱势修复可能' in view['thesis']
    source['facts']['rsi14']=55
    with pytest.raises(ValueError):build_release(raw,source)


def test_release_never_changes_buy_decision_or_unknown_claim():
    source,raw=sample();raw['decision']='BUY'
    with pytest.raises(ValueError):build_release(raw,source)
