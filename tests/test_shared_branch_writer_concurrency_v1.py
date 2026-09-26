from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/'.github/workflows'
TARGET='fix/native-private-execution-20260914'
GROUP='dsa-native-private-branch-writer'

def writer_workflows():
    rows=[]
    for p in sorted(WF.glob('*.y*ml')):
        text=p.read_text(encoding='utf-8')
        # Branch writers are workflows that explicitly target the shared branch
        # and have repository write permission plus a push command.
        if TARGET in text and 'contents: write' in text and re.search(r'git\s+push\b',text):
            rows.append((p,text))
    return rows

def test_all_native_private_branch_writers_share_one_queue():
    rows=writer_workflows()
    assert rows, 'NO_SHARED_BRANCH_WRITERS_DISCOVERED'
    bad=[]
    for p,text in rows:
        if f'group: {GROUP}' not in text or 'queue: max' not in text or 'cancel-in-progress: false' not in text:
            bad.append(p.name)
    assert not bad, f'UNSERIALIZED_SHARED_BRANCH_WRITERS:{bad}'

def test_known_current_writers_are_discovered():
    names={p.name for p,_ in writer_workflows()}
    required={
      '136-dsa-production-orchestrator-v1-runtime.yml',
      '137-dsa-simulation-journal-init.yml',
      '139-dsa-production-entry-v1.yml',
      '144-dsa-daily-o-formal-producer.yml',
      '145-dsa-daily-u-formal-producer.yml',
    }
    assert required <= names, sorted(required-names)

def test_no_force_push_in_shared_writer_set():
    for p,text in writer_workflows():
        assert 'push --force' not in text.lower(), p.name
        assert 'push -f ' not in text.lower(), p.name
