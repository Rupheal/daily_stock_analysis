import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from o_native_model_configuration import configure, VERSION


def test_native_config_contains_only_environment_secret_reference(tmp_path):
    env = configure(tmp_path, VERSION)
    config = json.loads(Path(env['LITELLM_CONFIG']).read_text())
    params = config['model_list'][0]['litellm_params']
    assert params['api_key'] == 'os.environ/LLM_DEEPSEEK_API_KEY'
    assert params['extra_body']['thinking'] == {'type': 'disabled'}
    assert env['DSA_EXPECT_THINKING'] == 'disabled'
    assert 'max_tokens' not in params and 'messages' not in params
    with pytest.raises(FileExistsError): configure(tmp_path, VERSION)


def test_unknown_configuration_rejected(tmp_path):
    with pytest.raises(ValueError): configure(tmp_path, 'unreviewed')


def test_wire_missing_thinking_blocked_before_any_request(monkeypatch, tmp_path):
    import httpx
    from deepseek_flash_cap010_guard import install_into_budget_guard
    import hk_budget_guard
    monkeypatch.setenv('DSA_EXPECT_THINKING', 'disabled')
    original = hk_budget_guard.ResearchBudget.admit
    try:
        install_into_budget_guard()
        budget = hk_budget_guard.ResearchBudget(tmp_path/'budget.json', limit='0.10',
            carry_upper='0', max_requests=1, model='deepseek-flash',host='api.deepseek.com')
        req = httpx.Request('POST','https://api.deepseek.com/chat/completions',
            json={'model':'deepseek-flash','messages':[],'max_tokens':8192})
        with pytest.raises(RuntimeError,match='NOT_PRESENT_ON_WIRE'): budget.admit(req,True)
        assert budget.state['requests'] == []
    finally: hk_budget_guard.ResearchBudget.admit = original
