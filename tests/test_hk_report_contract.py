"""Persistent risks, real rejected outputs and canonical execution are release gates."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.hk_report_contract import (REGISTRY, attach_report_contract, reviewed_events,
    audit_contract, execution_fields, deduplicate_events)
from src.services.market_data_integrity import enforce_daily_report, audit_daily_report


def context():
    return attach_report_contract({'code': 'HK01810', 'today': dict(
        date='2026-09-11', open=25.66, high=26.66, low=25.44, close=26.36, volume_ratio=.72)})


def report(ctx, mode='conditional_long'):
    events = ctx['hk_report_contract']['events']
    return {'success': True, 'dashboard': {
        'evidence_review': [{'event_id': e['id'], 'kind': e['kind'], 'status': e['status'],
            'source_urls': [e['sources'][0]['url']], 'assessment': '保留原证据边界，后续状态待核验。'} for e in events],
        'core_conclusion': {'position_advice': {}},
        'battle_plan': {'execution_basis': dict(mode=mode, entry_price=26., stop_price=25., position_pct=10.)
            if mode == 'conditional_long' else dict(mode='watch', entry_price=None, stop_price=None, position_pct=None),
            'sniper_points': {}, 'position_strategy': {}}}}


def test_unresolved_risks_survive_news_window_without_rewriting_publication():
    original = reviewed_events('hk01810')
    later = reviewed_events('1810.HK', datetime.now(timezone.utc)+timedelta(days=30))
    assert original == later
    assert any(e['published_at'].startswith('2026-09-09') and e['status'] == 'unresolved' for e in later)
    assert next(e for e in later if 'anthropic' in e['id'])['publication_precision'] == 'day'


@pytest.mark.parametrize('mutation', ['future', 'duplicate', 'false_resolution'])
def test_registry_rejects_false_chronology_and_unsupported_closure(tmp_path, mutation):
    registry = json.loads(REGISTRY.read_text())
    if mutation == 'future':
        registry['events'][0]['reviewed_at'] = '2099-01-01T00:00:00+00:00'
    elif mutation == 'duplicate':
        registry['events'].append(deepcopy(registry['events'][0]))
    else:
        registry['events'][0]['status'] = 'resolved'
    path = tmp_path/'registry.json'; path.write_text(json.dumps(registry))
    with pytest.raises(ValueError):
        reviewed_events('HK01810', registry_path=path)


@pytest.mark.parametrize('mutation', ['omit', 'status', 'kind', 'url', 'duplicate'])
def test_model_must_keep_risk_identity_state_and_real_provenance(mutation):
    ctx = context(); data = report(ctx); rows = data['dashboard']['evidence_review']
    if mutation == 'omit':
        rows.pop(0)
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif mutation == 'url':
        rows[0]['source_urls'] = ['https://invented.example/story']
    else:
        rows[0][mutation] = 'confirmed resolved'
    assert audit_contract(data, ctx)


@pytest.mark.parametrize('mode', ['conditional_long', 'watch'])
def test_one_definition_is_rendered_idempotently_before_consumers(mode):
    ctx = context(); data = report(ctx, mode)
    obj = SimpleNamespace(**data, data_sources='', raw_response=json.dumps(data))
    obj.to_dict = lambda: {k: v for k, v in vars(obj).items() if k != 'to_dict'}
    original = obj.raw_response
    assert enforce_daily_report(obj, ctx)['passed']
    rendered = deepcopy(obj.dashboard)
    assert enforce_daily_report(obj, ctx)['passed']
    assert obj.dashboard == rendered and obj.raw_response == original
    assert obj.dashboard['battle_plan']['sniper_points']
    if mode == 'conditional_long':
        assert '3.85%' in obj.dashboard['battle_plan']['position_strategy']['risk_control']
        assert '0.38%' in obj.dashboard['battle_plan']['position_strategy']['risk_control']


@pytest.mark.parametrize('field,value', [('entry_price', float('nan')), ('stop_price', float('inf')),
    ('position_pct', True), ('position_pct', 0), ('position_pct', 101), ('stop_price', 27)])
def test_invalid_execution_fails_closed(field, value):
    ctx = context(); data = report(ctx)
    data['dashboard']['battle_plan']['execution_basis'][field] = value
    assert any(f['code'] == 'invalid_structured_execution' for f in audit_contract(data, ctx))


def test_second_execution_definition_is_rejected_before_replacement():
    ctx = context(); data = report(ctx)
    data['dashboard']['battle_plan']['sniper_points'] = {'stop_loss': '25.44元立即离场'}
    obj = SimpleNamespace(**data, to_dict=lambda: data, raw_response='immutable bad output')
    assert not enforce_daily_report(obj, ctx)['passed']
    assert not obj.success and obj.dashboard is None and obj.action is None
    assert obj.raw_response == 'immutable bad output'


def test_known_translated_event_is_one_candidate_unknown_events_stay_explicit():
    rows = [{'title': '里昂：小米SkyNomad', 'url': 'https://news.futunn.com/post/1?lang=en'},
            {'title': 'CLSA Xiaomi SkyNomad', 'url': 'https://www.etnet.com.hk/article/2'},
            {'title': 'Another event', 'url': 'https://www.etnet.com.hk/article/3'}]
    result = deduplicate_events(rows)
    assert len(result) == 2 and len(result[0]['event_source_urls']) == 2
    assert result[0]['grouping_reviewed'] and not result[1]['grouping_reviewed']


@pytest.mark.parametrize('name', ['xiaomi_model_unapproved_20260912.json',
                                 'xiaomi_model_followup_unapproved_20260912.json'])
def test_authentic_failed_reports_do_not_pass_new_contract(name):
    fixture = json.loads((Path(__file__).parent/'fixtures'/name).read_text())
    ctx = attach_report_contract(fixture['context'], 'HK01810')
    audit = audit_daily_report(fixture['result'], ctx)
    assert not audit['passed']
    assert 'unresolved_risk_omitted' in {f['code'] for f in audit['findings']}
