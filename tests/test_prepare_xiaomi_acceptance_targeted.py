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
