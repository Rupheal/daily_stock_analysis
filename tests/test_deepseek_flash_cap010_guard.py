from decimal import Decimal
import pytest

from deepseek_flash_cap010_guard import (
    HARD_CAP_CNY, DEFAULT_INPUT_MARGIN_TOKENS, peak_upper_cny,
)


def test_historical_shape_with_margin_remains_below_cap():
    # Historical CHILD2 actual provider prompt_tokens=4687. This test does not
    # assume Run028 has the same prompt; Run028 must count its concrete request.
    assert peak_upper_cny(4687, 8192) < HARD_CAP_CNY


def test_cap_boundary_is_exact_and_fail_closed_ready():
    # With 8192 max output and a 2048-token safety margin, the largest counted
    # input that fits the 0.10 CNY peak envelope is 15184 tokens.
    assert peak_upper_cny(15184, 8192) == Decimal('0.100000')
    assert peak_upper_cny(15185, 8192) > HARD_CAP_CNY


def test_bad_counts_rejected():
    for value in (-1, 1.5, True):
        with pytest.raises(ValueError):
            peak_upper_cny(value, 8192)
    with pytest.raises(ValueError):
        peak_upper_cny(1, 0)
    with pytest.raises(ValueError):
        peak_upper_cny(1, 8192, margin_tokens=-1)


def test_default_margin_is_2048():
    assert DEFAULT_INPUT_MARGIN_TOKENS == 2048


def _fake_request():
    import httpx, json
    return httpx.Request(
        'POST','https://api.deepseek.com/chat/completions',
        content=json.dumps({
            'model':'deepseek-flash',
            'messages':[{'role':'user','content':'x'}],
            'max_tokens':8192,
        }).encode(),
        headers={'content-type':'application/json'},
    )


def test_default_cap_still_fails_closed_without_explicit_escalation(monkeypatch,tmp_path):
    import hk_budget_guard
    import deepseek_flash_cap010_guard as g
    monkeypatch.delenv(g.ALLOW_ESCALATION_ENV,raising=False)
    monkeypatch.delenv(g.AUTHORIZED_CEILING_ENV,raising=False)
    monkeypatch.setattr(g,'_official_input_tokens',lambda body:15185)
    g.install_into_budget_guard()
    b=hk_budget_guard.ResearchBudget(
        tmp_path/'b.json',limit='0.10',carry_upper='0',max_requests=1,
        model='deepseek-flash',host='api.deepseek.com')
    with pytest.raises(RuntimeError,match='PRE_SEND_CAP_EXCEEDED'):
        b.admit(_fake_request(),True)


def test_opt_in_dry_probe_reports_required_cap_without_send(monkeypatch,tmp_path):
    import hk_budget_guard
    import deepseek_flash_cap010_guard as g
    monkeypatch.setenv(g.ALLOW_ESCALATION_ENV,'1')
    monkeypatch.setenv(g.AUTHORIZED_CEILING_ENV,'2.00')
    monkeypatch.setenv('DSA_BUDGET_PROBE_ONLY','1')
    monkeypatch.setattr(g,'_official_input_tokens',lambda body:15185)
    required=g.peak_upper_cny(15185,8192)
    g.install_into_budget_guard()
    b=hk_budget_guard.ResearchBudget(
        tmp_path/'b.json',limit='0.10',carry_upper='0',max_requests=1,
        model='deepseek-flash',host='api.deepseek.com')
    with pytest.raises(RuntimeError,match='DRY_ENVELOPE_REQUIRES_CAP_RAISE'):
        b.admit(_fake_request(),True)
    assert b.state['requests'][0]['status']=='dry_envelope_requires_cap_raise'
    assert Decimal(b.state['requests'][0]['required_cap_cny'])==required
    assert Decimal(b.state['requests'][0]['authorized_ceiling_cny'])==Decimal('2.00')


def test_escalated_cap_must_be_within_authorized_ceiling(monkeypatch,tmp_path):
    import hk_budget_guard
    import deepseek_flash_cap010_guard as g
    monkeypatch.setenv(g.ALLOW_ESCALATION_ENV,'1')
    monkeypatch.setenv(g.AUTHORIZED_CEILING_ENV,'2.00')
    monkeypatch.setenv('DSA_BUDGET_PROBE_ONLY','1')
    monkeypatch.setattr(g,'_official_input_tokens',lambda body:15185)
    required=g.peak_upper_cny(15185,8192)
    g.install_into_budget_guard()
    b=hk_budget_guard.ResearchBudget(
        tmp_path/'b.json',limit=str(required),carry_upper='0',max_requests=1,
        model='deepseek-flash',host='api.deepseek.com')
    with pytest.raises(RuntimeError,match='DRY_ENVELOPE_COMPLETE_NO_SEND'):
        b.admit(_fake_request(),True)
    assert b.state['requests'][0]['status']=='dry_envelope_validated_not_sent'
    assert Decimal(b.state['requests'][0]['hard_cap_cny'])==required


def test_escalated_limit_above_user_ceiling_rejected(monkeypatch,tmp_path):
    import hk_budget_guard
    import deepseek_flash_cap010_guard as g
    monkeypatch.setenv(g.ALLOW_ESCALATION_ENV,'1')
    monkeypatch.setenv(g.AUTHORIZED_CEILING_ENV,'2.00')
    monkeypatch.setattr(g,'_official_input_tokens',lambda body:15185)
    g.install_into_budget_guard()
    b=hk_budget_guard.ResearchBudget(
        tmp_path/'b.json',limit='2.01',carry_upper='0',max_requests=1,
        model='deepseek-flash',host='api.deepseek.com')
    with pytest.raises(RuntimeError,match='LIMIT_OUTSIDE_AUTHORIZED_CEILING'):
        b.admit(_fake_request(),True)
