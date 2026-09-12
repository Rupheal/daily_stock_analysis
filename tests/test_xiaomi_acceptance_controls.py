"""Acceptance boundaries must fail before a second paid request or bad input."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from scripts.prepare_xiaomi_acceptance import compare_prices
from scripts.run_xiaomi_acceptance import SingleCallGuard, validate_model_input, record_report_review


def request(**overrides):
    body = dict(model='test-model', stream=False, max_tokens=8192, messages=[])
    body.update(overrides)
    return httpx.Request('POST', 'https://model.example/chat/completions', json=body)


def test_guard_requires_input_acceptance_and_allows_only_one_wire_request():
    guard = SingleCallGuard('https://model.example', 'test-model')
    with pytest.raises(RuntimeError):
        guard.admit(request())
    guard.input_validated = True
    assert guard.admit(request())
    with pytest.raises(RuntimeError):
        guard.admit(request())
    assert guard.sent == 1


@pytest.mark.parametrize('overrides', [dict(model='other-model'), dict(stream=True),
    dict(max_tokens=8193), dict(messages=['x'*100001])])
def test_guard_rejects_unbudgeted_request_before_counting_it(overrides):
    guard = SingleCallGuard('https://model.example', 'test-model')
    guard.input_validated = True
    with pytest.raises(RuntimeError):
        guard.admit(request(**overrides))
    assert guard.sent == 0


def test_guard_records_raw_provider_usage_without_normalizing_tokens():
    guard = SingleCallGuard('https://model.example', 'test-model')
    raw = {'prompt_tokens': 300, 'completion_tokens': 120, 'total_tokens': 420}
    guard.capture(httpx.Response(200, json={'model': 'test-model', 'usage': raw}))
    assert guard.raw_usage == raw
    assert guard.raw_response['usage'] == raw


def test_changed_model_input_or_expired_preflight_is_rejected():
    today = dict(date='2026-09-11', open=25.66, high=26.66, low=25.44, close=26.36,
                 volume=113533443, ma5=26.62, ma10=27.22, ma20=27.39, volume_ratio=0.72)
    context = {'today': today}
    preflight = dict(passed=True, prepared_at=datetime.now(timezone.utc).isoformat(),
                     target='2026-09-11', today=dict(today))
    validate_model_input(context, preflight)
    context['fundamental_context'] = {'earnings': {'data': {'financial_report': {'revenue': 123}}}}
    with pytest.raises(ValueError, match='Unverified HK financial'):
        validate_model_input(context, preflight)
    context.pop('fundamental_context')
    context['today']['close'] = 30
    with pytest.raises(ValueError, match='differs'):
        validate_model_input(context, preflight)
    preflight['prepared_at'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    with pytest.raises(ValueError, match='expired'):
        validate_model_input(context, preflight)


def test_independent_prices_require_exact_volume_and_finite_values():
    dates = pd.bdate_range(end='2026-09-11', periods=60).strftime('%Y-%m-%d')
    primary = pd.DataFrame({'date': dates, 'open': 25., 'high': 27., 'low': 24., 'close': 26., 'volume': 100.})
    other = primary.copy()
    assert compare_prices(primary, other, '2026-09-11') == 60
    other.loc[59, 'volume'] += 1
    with pytest.raises(ValueError, match='volume'):
        compare_prices(primary, other, '2026-09-11')
    other = primary.copy()
    other.loc[58, 'open'] = float('nan')
    with pytest.raises(ValueError, match='Missing'):
        compare_prices(primary, other, '2026-09-11')


def test_failed_native_report_is_retained_without_publishing_its_execution(tmp_path):
    from types import SimpleNamespace
    from src.services.market_data_integrity import enforce_daily_report
    obj = SimpleNamespace(success=True, raw_response='original response', dashboard={'battle_plan': {
        'execution_basis': {'entry_price': 26.62, 'stop_price': 25.40},
        'sniper_points': {'ideal_buy': '26.60元'}}})
    obj.to_dict = lambda: {key: value for key, value in vars(obj).items() if key != 'to_dict'}
    context = {'today': dict(open=25.66, high=26.66, low=25.44, close=26.36)}
    audit = record_report_review(obj, context, enforce_daily_report, tmp_path)
    saved = json.loads((tmp_path/'report-review.json').read_text())
    assert not audit['passed']
    assert saved['before_enforcement']['dashboard']['battle_plan']['execution_basis']['entry_price'] == 26.62
    assert saved['before_enforcement']['raw_response'] == 'original response'
    assert not saved['after_enforcement']['success']
    assert saved['after_enforcement']['dashboard'] is None
