from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import prepare_xiaomi_acceptance_targeted as targeted


def test_target_adapter_injects_frozen_rule(monkeypatch, tmp_path):
    captured = {}

    class Resolved:
        target_session = datetime(2026, 9, 15, tzinfo=timezone.utc).date()

    monkeypatch.setattr(targeted, 'resolve_target_session', lambda _: Resolved())

    def fake_prepare(**kwargs):
        captured['resolved'] = targeted.base.get_effective_trading_date('hk')
        root = Path(kwargs['root'])
        root.mkdir(parents=True, exist_ok=True)
        return {'target': '2026-09-15'}

    monkeypatch.setattr(targeted.base, 'prepare', fake_prepare)
    audit, receipt = targeted.prepare_targeted(root=tmp_path)
    assert captured['resolved'].isoformat() == '2026-09-15'
    assert audit['target'] == '2026-09-15'
    assert receipt['target_match'] is True
    assert receipt['rule_version'] == targeted.RULE_VERSION
    assert receipt['yahoo_retrieval_boundary'] == '2026-09-16'
    assert receipt['yahoo_end_semantics'] == 'exclusive'
    assert receipt['yahoo_repair_enabled'] is True
    assert receipt['model_http_requests'] == 0


def test_target_adapter_fails_if_preflight_does_not_use_frozen_target(monkeypatch, tmp_path):
    class Resolved:
        target_session = datetime(2026, 9, 15, tzinfo=timezone.utc).date()

    monkeypatch.setattr(targeted, 'resolve_target_session', lambda _: Resolved())
    monkeypatch.setattr(targeted.base, 'prepare', lambda **kwargs: {'target': '2026-09-14'})

    try:
        targeted.prepare_targeted(root=tmp_path)
    except ValueError as exc:
        assert str(exc) == 'PREFLIGHT_TARGET_SESSION_CONTRACT_MISMATCH'
    else:
        raise AssertionError('contract mismatch must fail closed')


def test_bounded_yahoo_history_replaces_period_with_explicit_exclusive_end_and_repair():
    expected = datetime(2026, 9, 15, tzinfo=timezone.utc).date()
    got = targeted._bounded_history_kwargs(expected, {
        'period': '6mo',
        'auto_adjust': True,
        'actions': True,
        'timeout': 20,
    })
    assert 'period' not in got
    assert got['start'] == '2026-02-27'
    assert got['end'] == '2026-09-16'
    assert got['repair'] is True
    assert got['auto_adjust'] is True
    assert got['actions'] is True
    assert got['timeout'] == 20


def test_bounded_yahoo_history_preserves_already_explicit_request():
    expected = datetime(2026, 9, 15, tzinfo=timezone.utc).date()
    original = {'start': '2026-03-01', 'end': '2026-09-16', 'auto_adjust': True}
    assert targeted._bounded_history_kwargs(expected, original) == original
