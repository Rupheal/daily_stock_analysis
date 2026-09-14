"""Fail-closed host boundary tests; no real model calls."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('private_probe', Path(__file__).parents[1]/'scripts/run_hk_original_private_probe.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ENV = {'LLM_DEEPSEEK_API_KEY': 'synthetic-only', 'LLM_DEEPSEEK_BASE_URL': 'https://example.invalid', 'LLM_DEEPSEEK_MODELS': 'fixture'}


def gate(tmp_path, env=None, head='frozen', dirty='', output=None):
    with patch.object(m.subprocess, 'check_output', side_effect=[head, dirty]):
        return m.host_gate(tmp_path/'original', output or tmp_path/'new', 'frozen', ENV if env is None else env)


def test_missing_credential_fails_without_disclosure(tmp_path):
    result = gate(tmp_path, {})
    assert 'PRIVATE_HOST_MODEL_CREDENTIAL_MISSING' in result
    assert not (tmp_path/'new').exists()


def test_cloud_route_rejected_even_with_credentials(tmp_path):
    assert 'PUBLIC_CI_ROUTE_DISABLED' in gate(tmp_path, {**ENV, 'GITHUB_ACTIONS': 'true'})


def test_wrong_or_dirty_upstream_rejected(tmp_path):
    assert 'UPSTREAM_COMMIT_MISMATCH' in gate(tmp_path, head='wrong')
    assert 'UPSTREAM_TRACKED_SOURCE_CHANGED' in gate(tmp_path, dirty='src/analyzer.py')


def test_no_replay_or_repo_output(tmp_path):
    (tmp_path/'new').mkdir()
    assert 'OUTPUT_EXISTS_NO_REPLAY' in gate(tmp_path)
    assert 'OUTPUT_INSIDE_REPOSITORY' in gate(tmp_path, output=tmp_path/'original'/'raw')


def test_symlink_and_clean_private_host(tmp_path):
    assert gate(tmp_path) == []
    (tmp_path/'target').mkdir()
    (tmp_path/'new').symlink_to(tmp_path/'target', target_is_directory=True)
    assert 'OUTPUT_SYMLINK_FORBIDDEN' in gate(tmp_path)


def test_child_output_stays_private(tmp_path, capsys):
    root = tmp_path/'private'
    fixture = tmp_path/'input.json'
    fixture.write_text('{}')
    args = ['probe', '--checkout', str(tmp_path/'original'), '--expected-commit', 'frozen',
            '--output', str(root), '--run-id', 'fixture-run', '--preflight', str(fixture), '--limit-cny', '1']
    def fake_run(command, **kwargs):
        assert kwargs['stderr'] is kwargs['stdout']
        assert kwargs['env']['ENV_FILE'] == '/dev/null'
        assert 'OTHER_API_KEY' not in kwargs['env']
        kwargs['stdout'].write('SYNTHETIC_RAW_RESPONSE_MARKER\n')
        return type('Result', (), {'returncode': 0})()
    old_umask = m.os.umask(0o077)
    try:
        with patch.object(m.sys, 'argv', args), patch.dict(m.os.environ, {**ENV, 'OTHER_API_KEY':'fixture-other'}, clear=True), patch.object(m, 'host_gate', return_value=[]), patch.object(m.subprocess, 'run', side_effect=fake_run):
            assert m.main() == 0
    finally:
        m.os.umask(old_umask)
    assert 'SYNTHETIC_RAW_RESPONSE_MARKER' not in capsys.readouterr().out
    assert 'SYNTHETIC_RAW_RESPONSE_MARKER' in (root/'private-process.log').read_text()
    assert root.stat().st_mode & 0o077 == 0
    assert m.json.loads((root/'manifest.json').read_text())['trade_approved'] is False
