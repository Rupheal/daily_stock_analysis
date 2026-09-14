"""Static boundary checks; no credentials, dispatch, model calls or ledger writes."""
import ast
from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / '.github/workflows/43-native-private-single-stock.yml'
UPSTREAM = '089d9d26d68f8b839ea5a74a3784e4402925f8b7'


def steps():
    return yaml.load(PATH.read_text(), Loader=yaml.BaseLoader)['jobs']['native-private']['steps']


def test_private_order_claim_before_model_then_save():
    s = steps(); names = [x.get('name', '') for x in s]
    claim = names.index('Persist one-call intent before native request')
    call = names.index('One frozen-upstream native request with raw console capture')
    save = names.index('Persist original byte archive to Drive and restore-verify')
    assert claim < call and save == call + 1
    assert 'always()' in s[save]['if'] and "'failure'" in s[save]['if']
    assert not any('text-only' in n for n in names)


def test_upstream_and_native_arguments_unchanged():
    s = steps()
    original = [x for x in s if x.get('with', {}).get('path') == 'original'][0]
    assert original['with']['ref'] == UPSTREAM
    native = next(x for x in s if x.get('id') == 'native_call')
    for expected in ['run_hk_original_model_probe.py', '--expected-commit '+UPSTREAM,
                     '--limit-cny 2', '--carry-upper-cny 0.060156',
                     '> /tmp/native-evidence/native-stdout.log 2> /tmp/native-evidence/native-stderr.log']:
        assert expected in native['run']


def test_no_public_raw_artifacts_or_direct_secret_echo():
    text = PATH.read_text()
    assert 'upload-artifact' not in text
    assert 'echo "$LLM_DEEPSEEK_API_KEY"' not in text
    assert "assert_absent('ART-DSA-RUN013-NATIVE-CLAIM')" in text
    assert 'reserve_native_call(' in text


def test_workflows_serialize_same_writer_and_no_schedule():
    for n in ['43-native-private-single-stock.yml', '44-drive-storage-readiness.yml']:
        d = yaml.load((PATH.parent / n).read_text(), Loader=yaml.BaseLoader)
        assert 'schedule' not in d['on']
        assert d['concurrency'] == {'group': 'dsa-drive-evidence-writer', 'cancel-in-progress': 'false'}
        assert d['permissions'] == {'contents': 'read'}


def test_all_embedded_python_compiles_without_execution():
    for step in steps():
        run = step.get('run', '')
        for m in re.finditer(r"python - <<'(\w+)'\n(.*?)\n\1(?:\n|$)", run, re.S):
            ast.parse(m.group(2))
