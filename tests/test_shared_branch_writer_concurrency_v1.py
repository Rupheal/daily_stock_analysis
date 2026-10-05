from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / '.github/workflows'
TARGET = 'fix/native-private-execution-20260914'
GROUP = 'dsa-native-private-branch-writer'
PUSH = re.compile(r'\bgit\s+push\b')
OTHER_PUSH = re.compile(r'\bgit\b(?:(?!\bgit\b)[^\n])*\bpush\b')
VARIABLE_PUSH = re.compile(r'["\']?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?["\']?\s+push\b')
SHELL_FUNCTION = re.compile(r'\b(?:function\s+[A-Za-z_]\w*|[A-Za-z_]\w*\s*\(\)\s*\{)')
INDIRECT_PUSH_CALL = re.compile(r'(?m)^[ \t]*(?:publish|push|commit|sync)[A-Za-z0-9_.-]*\s+[^\n]*\bpush\b')
BRANCH = re.compile(r'^[A-Za-z0-9._/-]+$')


@dataclass(frozen=True)
class WriteSemantics:
    kind: str
    destinations: tuple[str, ...] = ()
    write_commands: tuple[str, ...] = ()
    force_commands: tuple[str, ...] = ()
    trigger: str = ''
    concurrency_group: str = ''
    cancel_in_progress: object = None
    queue: str = ''


def _triggers(data):
    events = data.get('on', data.get(True, {}))
    return events if isinstance(events, dict) else {}


def _push_branches(events):
    push = events.get('push', {}) or {}
    branches = push.get('branches', []) if isinstance(push, dict) else []
    if isinstance(branches, str):
        branches = [branches]
    return branches


def _checkout_for_path(checkouts, directory):
    directory = str(directory or '.').strip('./') or '.'
    for path, ref, repository in reversed(checkouts):
        if path == directory:
            return ref, repository
    return None


def _implicit_destination(checkouts, directory, events):
    checkout = _checkout_for_path(checkouts, directory)
    if checkout is None:
        return None
    ref, repository = checkout
    if repository not in (None, '', '${{ github.repository }}'):
        return None
    if ref:
        return ref if isinstance(ref, str) and BRANCH.fullmatch(ref) else None
    # A manual dispatch can select the shared branch even when push filters
    # name a different branch. That branch must join the same writer queue.
    if 'workflow_dispatch' in events:
        return f'github.ref_name (workflow_dispatch includes {TARGET})'
    branches = _push_branches(events)
    return branches[0] if len(branches) == 1 and BRANCH.fullmatch(branches[0]) else None


def _parse_push(command, checkouts, directory, events):
    if '$' in command or '`' in command:
        return None, False
    try:
        words = shlex.split(command)
    except ValueError:
        return None, False
    if words[:2] != ['git', 'push']:
        return None, False
    args = words[2:]
    force = any(arg.startswith(('--force', '--mirror')) or
                (arg.startswith('-') and not arg.startswith('--') and 'f' in arg[1:]) or
                arg.startswith('+') for arg in args)
    positional = [arg for arg in args if not arg.startswith('-')]
    if not positional:
        return _implicit_destination(checkouts, directory, events), force
    if len(positional) == 2 and positional[0] == 'origin':
        match = re.fullmatch(r'HEAD:([A-Za-z0-9._/-]+)', positional[1])
        if match:
            return match.group(1), force
    return None, force


def _push_commands(run):
    commands = []
    for match in PUSH.finditer(run):
        line_end = run.find('\n', match.start())
        if line_end == -1:
            line_end = len(run)
        tail = run[match.start():line_end]
        tail = re.split(r'\s*(?:;|&&|\|\||#)', tail, maxsplit=1)[0]
        commands.append(tail.strip('\r'))
    return commands


def classify_workflow_text(text):
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError('WORKFLOW_YAML_NOT_MAPPING')
    events = _triggers(data)
    concurrency = data.get('concurrency') or {}
    if not isinstance(concurrency, dict):
        concurrency = {}
    trigger = ','.join(str(event) for event in events)
    common = dict(trigger=trigger, concurrency_group=str(concurrency.get('group', '')),
                  cancel_in_progress=concurrency.get('cancel-in-progress'),
                  queue=str(concurrency.get('queue', '')))
    destinations, commands, forced = [], [], []
    has_write_permission = data.get('permissions', {}).get('contents') == 'write' if isinstance(data.get('permissions'), dict) else False
    indirect = False
    unresolved_write_signal = False
    uses_only_release_actions = True
    for job in (data.get('jobs') or {}).values():
        if not isinstance(job, dict):
            continue
        permissions = job.get('permissions') or {}
        has_write_permission |= isinstance(permissions, dict) and permissions.get('contents') == 'write'
        if job.get('uses'):
            indirect = True
            unresolved_write_signal = True
        checkouts = []
        shell_checkout_changed_head = False
        for step in job.get('steps', []):
            if not isinstance(step, dict):
                continue
            uses = str(step.get('uses', ''))
            if uses.startswith('actions/checkout@'):
                with_ = step.get('with') or {}
                if not isinstance(with_, dict):
                    indirect = True
                    continue
                checkouts.append((str(with_.get('path', '.')).strip('./') or '.',
                                  with_.get('ref'), with_.get('repository')))
            elif uses.startswith('./.github/workflows/'):
                indirect = True
            elif uses and not uses.startswith(('actions/', 'softprops/action-gh-release@',
                                               'anothrNick/github-tag-action@')):
                uses_only_release_actions = False
            run = step.get('run') or ''
            if not isinstance(run, str):
                indirect = True
                continue
            changes_head = bool(re.search(r'\bgit\s+(?:checkout|switch|reset|branch)\b|\bcd\s+\S+', run))
            if any(len(OTHER_PUSH.findall(line)) > len(PUSH.findall(line)) or
                   len(INDIRECT_PUSH_CALL.findall(line)) > len(PUSH.findall(line))
                   for line in run.splitlines()) or VARIABLE_PUSH.search(run) or \
                    SHELL_FUNCTION.search(run):
                indirect = True
            if any(len(OTHER_PUSH.findall(line)) > len(PUSH.findall(line)) or
                   len(INDIRECT_PUSH_CALL.findall(line)) > len(PUSH.findall(line))
                   for line in run.splitlines()) or VARIABLE_PUSH.search(run):
                unresolved_write_signal = True
            if re.search(r'\bgh\s+api\b[^\n]*--method\s+(?:POST|PUT|PATCH|DELETE)\b', run, re.I):
                unresolved_write_signal = True
            if SHELL_FUNCTION.search(run):
                indirect = True
            for command in _push_commands(run):
                explicit_ref = bool(re.search(r'\bgit\s+push\b.*\bHEAD:[A-Za-z0-9._/-]+', command))
                if shell_checkout_changed_head or (changes_head and not explicit_ref):
                    indirect = True
                destination, force = _parse_push(command, checkouts,
                                                  step.get('working-directory'), events)
                commands.append(command.strip())
                destinations.append(destination)
                if force:
                    forced.append(command.strip())
            if run and re.search(r'\b(?:push|publish)_branch\b|\bgh\s+api\b', run):
                indirect = True
                if re.search(r'\b(?:push|publish)_branch\b', run):
                    unresolved_write_signal = True
            shell_checkout_changed_head |= changes_head
    if not has_write_permission and not commands:
        kind = 'UNKNOWN_WRITE_SEMANTICS' if unresolved_write_signal else 'NON_TARGET_WRITER'
        return WriteSemantics(kind, tuple(str(x or '?') for x in destinations),
                              tuple(commands), tuple(forced), **common)
    if indirect or any(destination is None for destination in destinations):
        kind = 'UNKNOWN_WRITE_SEMANTICS'
    elif commands:
        kind = ('SHARED_TARGET_WRITER' if any(
            destination == TARGET or f'includes {TARGET}' in destination
            for destination in destinations) else 'NON_TARGET_WRITER')
    elif uses_only_release_actions and any(name in text for name in
            ('anothrNick/github-tag-action@', 'softprops/action-gh-release@')):
        kind = 'NON_TARGET_WRITER'
    else:
        kind = 'UNKNOWN_WRITE_SEMANTICS'
    if commands and not has_write_permission:
        kind = 'UNKNOWN_WRITE_SEMANTICS'
    return WriteSemantics(kind, tuple(str(x or '?') for x in destinations),
                          tuple(commands), tuple(forced), **common)


def workflow_inventory():
    return [(path, classify_workflow_text(path.read_text(encoding='utf-8')))
            for path in sorted(WF.glob('*.y*ml'))]


def writer_workflows():
    return [(path, path.read_text(encoding='utf-8'))
            for path, result in workflow_inventory()
            if result.kind == 'SHARED_TARGET_WRITER']


def _patch_workflow_root(monkeypatch, path):
    monkeypatch.setattr(sys.modules[__name__], 'WF', path)


def _has_shared_group(group):
    if group == GROUP:
        return True
    expected = ("${{ github.ref == 'refs/heads/" + TARGET + "' && '" +
                GROUP + "' || '")
    return re.fullmatch(re.escape(expected) + r"[^']+' }}", group) is not None


def _serialized_for_result(result):
    if result.concurrency_group == GROUP:
        return True
    manual_ref_destinations = (result.trigger and 'workflow_dispatch' in result.trigger and
        result.destinations and all(destination.startswith('github.ref_name (workflow_dispatch includes ')
                                    for destination in result.destinations))
    return manual_ref_destinations and _has_shared_group(result.concurrency_group)


def test_all_native_private_branch_writers_share_one_queue():
    inventory = workflow_inventory()
    unknown = [path.name for path, result in inventory
               if result.kind == 'UNKNOWN_WRITE_SEMANTICS']
    assert not unknown, f'UNKNOWN_WRITE_SEMANTICS:{unknown}'
    writers = [(path, result) for path, result in inventory
               if result.kind == 'SHARED_TARGET_WRITER']
    assert writers, 'NO_SHARED_BRANCH_WRITERS_DISCOVERED'
    bad = [path.name for path, result in writers
           if not _serialized_for_result(result) or
           result.cancel_in_progress is not False or result.queue != 'max']
    assert not bad, f'UNSERIALIZED_SHARED_BRANCH_WRITERS:{bad}'


def test_known_current_writers_are_discovered():
    names = {path.name for path, _ in writer_workflows()}
    required = {
        '136-dsa-production-orchestrator-v1-runtime.yml',
        '137-dsa-simulation-journal-init.yml',
        '139-dsa-production-entry-v1.yml',
        '144-dsa-daily-o-formal-producer.yml',
        '145-dsa-daily-u-formal-producer.yml',
    }
    assert required <= names, sorted(required - names)


def test_no_force_push_in_shared_writer_set():
    bad = [f'{path.name}:{command}' for path, result in workflow_inventory()
           if result.kind == 'SHARED_TARGET_WRITER'
           for command in result.force_commands]
    assert not bad, f'HISTORY_REWRITING_PUSH:{bad}'


def _fixture(*, branch=TARGET, checkout_ref=None, checkout_path=None,
             persist_credentials=True, commands='git push', extra_checkout='',
             dispatch=False, publish_directory=None):
    checkout = '      - uses: actions/checkout@v5\n'
    options = []
    if checkout_ref:
        options.append(f'          ref: {checkout_ref}')
    if checkout_path:
        options.append(f'          path: {checkout_path}')
    if not persist_credentials:
        options.append('          persist-credentials: false')
    if options:
        checkout += '        with:\n' + '\n'.join(options) + '\n'
    return (
        f'name: fixture\non:\n  push:\n    branches: [{branch}]\n'
        + ('  workflow_dispatch:\n' if dispatch else '')
        + 'permissions:\n  contents: write\n'
        + 'concurrency:\n  group: dsa-native-private-branch-writer\n'
          '  cancel-in-progress: false\n  queue: max\n'
        + 'jobs:\n  publish:\n    runs-on: ubuntu-latest\n    steps:\n'
        + checkout + extra_checkout
        + '      - name: Publish\n'
        + (f'        working-directory: {publish_directory or checkout_path}\n'
           if publish_directory or checkout_path else '')
        + '        run: |\n'
        + '\n'.join(f'          {line}' for line in commands.splitlines()) + '\n'
    )


def test_dashboard_read_source_is_not_write_destination(tmp_path, monkeypatch):
    dashboard = _fixture(
        checkout_ref=TARGET, checkout_path='authority', persist_credentials=False,
        extra_checkout='      - uses: actions/checkout@v5\n'
                       '        with:\n'
                       '          ref: research/dsa-dashboard-v019-20260918\n'
                       '          path: dashboard\n',
        publish_directory='dashboard',
        commands='git push origin HEAD:research/dsa-dashboard-v019-20260918',
    )
    (tmp_path / 'dashboard.yml').write_text(dashboard)
    _patch_workflow_root(monkeypatch, tmp_path)
    assert [p.name for p, _ in writer_workflows()] == []
    assert classify_workflow_text(dashboard).kind == 'NON_TARGET_WRITER'


def test_explicit_and_implicit_shared_destinations():
    explicit = _fixture(commands=f'git push origin HEAD:{TARGET}')
    implicit = _fixture(commands='git push', checkout_ref=TARGET)
    assert classify_workflow_text(explicit).kind == 'SHARED_TARGET_WRITER'
    assert classify_workflow_text(implicit).kind == 'SHARED_TARGET_WRITER'


def test_manual_dispatch_implicit_writer_can_select_shared_target():
    text = _fixture(branch='research/other', dispatch=True, commands='git push')
    assert classify_workflow_text(text).kind == 'SHARED_TARGET_WRITER'


def test_unrelated_explicit_destination():
    text = _fixture(commands='git push origin HEAD:research/other')
    assert classify_workflow_text(text).kind == 'NON_TARGET_WRITER'


def test_unknown_variable_destination_and_indirection_fail_closed(tmp_path, monkeypatch):
    cases = [
        _fixture(commands='git push origin HEAD:$TARGET_BRANCH'),
        _fixture(commands='publish_branch "$TARGET_BRANCH"'),
        _fixture(commands='git push origin HEAD:${{ inputs.branch }}'),
        _fixture(commands='git -C research push origin HEAD:$TARGET_BRANCH'),
        _fixture(commands='git -c push.default=current push origin HEAD:$TARGET'),
        _fixture(commands=f'git push origin HEAD:research/other; '
                          f'git -c push.default=current push origin HEAD:{TARGET}'),
        _fixture(commands=f'git push origin HEAD:research/other\n'
                          '"$GIT" push origin HEAD:fix/native-private-execution-20260914'),
        _fixture(commands=f'git push origin HEAD:research/other\n'
                          'function publish_it() { command git "$@"; }\n'
                          'publish_it push origin HEAD:fix/native-private-execution-20260914'),
        _fixture(commands=f'git push origin HEAD:research/other; '
                          'publish_it() { "$GIT" "$@"; }; '
                          'publish_it push origin HEAD:fix/native-private-execution-20260914'),
        'name: indirect\non:\n  workflow_dispatch:\n'
        'permissions:\n  contents: write\n'
        'jobs:\n  publish:\n    uses: ./.github/workflows/indirect-writer.yml\n',
        _fixture(commands=f'git push origin HEAD:{TARGET}\n'
                          'git push origin HEAD:$SECOND_BRANCH'),
    ]
    for i, case in enumerate(cases):
        assert classify_workflow_text(case).kind == 'UNKNOWN_WRITE_SEMANTICS', i
    (tmp_path / 'unknown.yml').write_text(cases[0])
    _patch_workflow_root(monkeypatch, tmp_path)
    import pytest
    with pytest.raises(AssertionError, match='UNKNOWN_WRITE_SEMANTICS'):
        test_all_native_private_branch_writers_share_one_queue()


def test_indirect_api_mutation_is_unknown_without_explicit_write_permission():
    text = _fixture(commands='gh api --method PATCH repos/example/repo/git/refs')
    text = text.replace('contents: write', 'contents: read')
    assert classify_workflow_text(text).kind == 'UNKNOWN_WRITE_SEMANTICS'


def test_second_push_to_shared_target_is_discovered():
    text = _fixture(commands=f'git push origin HEAD:research/other\ngit push origin HEAD:{TARGET}')
    assert classify_workflow_text(text).kind == 'SHARED_TARGET_WRITER'
    assert len(classify_workflow_text(text).write_commands) == 2


def test_second_push_on_same_shell_line_is_discovered():
    text = _fixture(commands=f'git push origin HEAD:research/other; git push origin HEAD:{TARGET}')
    result = classify_workflow_text(text)
    assert result.kind == 'SHARED_TARGET_WRITER'
    assert len(result.write_commands) == 2


def test_implicit_push_after_shell_branch_switch_is_unknown():
    text = _fixture(commands='git checkout research/other\ngit push')
    assert classify_workflow_text(text).kind == 'UNKNOWN_WRITE_SEMANTICS'


@pytest.mark.parametrize('command', [
    f'git push --force origin HEAD:{TARGET}',
    f'git push -f origin HEAD:{TARGET}',
    f'git push --force-with-lease origin HEAD:{TARGET}',
    f'git push origin HEAD:{TARGET} --force-with-lease',
])
def test_history_rewriting_forms_are_rejected(tmp_path, monkeypatch, command):
    (tmp_path / 'force.yml').write_text(_fixture(commands=command))
    _patch_workflow_root(monkeypatch, tmp_path)
    with pytest.raises(AssertionError, match='HISTORY_REWRITING_PUSH'):
        test_no_force_push_in_shared_writer_set()


def test_new_shared_writer_is_discovered_repository_wide(tmp_path, monkeypatch):
    (tmp_path / 'new.yml').write_text(_fixture(commands=f'git push origin HEAD:{TARGET}'))
    _patch_workflow_root(monkeypatch, tmp_path)
    assert [p.name for p, _ in writer_workflows()] == ['new.yml']


def test_real_dashboard_stays_outside_shared_writer_queue():
    result = classify_workflow_text((WF / 'dsa-dashboard-v019-sync.yml').read_text())
    assert result.kind == 'NON_TARGET_WRITER'
    assert result.destinations == ('research/dsa-dashboard-v019-20260918',)
    assert result.concurrency_group == 'dsa-dashboard-v019-sanitized-sync'


def test_shared_group_expression_must_select_exact_target():
    expected = ("${{ github.ref == 'refs/heads/" + TARGET + "' && '" +
                GROUP + "' || 'research-group' }}")
    assert _has_shared_group(expected)
    assert not _has_shared_group(expected.replace(' == ', ' != '))
    assert not _has_shared_group(expected.replace(GROUP, 'wrong-group'))
    assert not _has_shared_group(expected + " || 'dsa-native-private-branch-writer'")


def test_ref_conditional_group_does_not_serialize_explicit_shared_push_from_other_ref():
    text = _fixture(branch='research/other',
                    commands=f'git push origin HEAD:{TARGET}')
    result = classify_workflow_text(text)
    conditional = ("${{ github.ref == 'refs/heads/" + TARGET + "' && '" +
                   GROUP + "' || 'research-group' }}")
    result = WriteSemantics(result.kind, result.destinations, result.write_commands,
                            result.force_commands, result.trigger, conditional,
                            False, 'max')
    assert not _serialized_for_result(result)
