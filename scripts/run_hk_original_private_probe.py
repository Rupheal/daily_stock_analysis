"""Private-host envelope around the existing native one-stock observer.

No upstream prompts, inputs, scores or results are rewritten. Never use this
envelope in public CI: it has no public-artifact export route.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def host_gate(checkout, output, expected_commit, env):
    """Read-only checks; never inspect or print credential values."""
    failures = []
    if env.get('GITHUB_ACTIONS'):
        failures.append('PUBLIC_CI_ROUTE_DISABLED')
    if not env.get('LLM_DEEPSEEK_API_KEY'):
        failures.append('PRIVATE_HOST_MODEL_CREDENTIAL_MISSING')
    for key in ('LLM_DEEPSEEK_BASE_URL', 'LLM_DEEPSEEK_MODELS'):
        if not env.get(key):
            failures.append(key + '_MISSING')
    target = Path(output).absolute()
    if target.exists():
        failures.append('OUTPUT_EXISTS_NO_REPLAY')
    if any(p.is_symlink() for p in [target, *target.parents]):
        failures.append('OUTPUT_SYMLINK_FORBIDDEN')
    source_roots = (Path(checkout).resolve(), Path(__file__).resolve().parents[1])
    if any(target.resolve().is_relative_to(p) for p in source_roots):
        failures.append('OUTPUT_INSIDE_REPOSITORY')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
    if head != expected_commit:
        failures.append('UPSTREAM_COMMIT_MISMATCH')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=checkout, text=True).strip():
        failures.append('UPSTREAM_TRACKED_SOURCE_CHANGED')
    return failures


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkout', type=Path, required=True)
    p.add_argument('--expected-commit', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--preflight', type=Path)
    p.add_argument('--limit-cny')
    p.add_argument('--carry-upper-cny', default='0')
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args()
    failures = host_gate(a.checkout, a.output, a.expected_commit, os.environ)
    if a.check_only or failures:
        print(json.dumps({'run_id': a.run_id, 'host_gate': 'BLOCKED' if failures else 'READY',
                          'failures': failures, 'model_requests': 0,
                          'live_native_acceptance': False}))
        return 2 if failures else 0
    if not a.preflight or not a.limit_cny:
        p.error('live execution requires a validated preflight and per-run budget')
    # No dotenv search, notifications, alternate providers or public console logs.
    env = {k: v for k, v in os.environ.items() if not any(
        s in k.upper() for s in ('TOKEN', 'SECRET', 'API_KEY', 'WEBHOOK', 'PASSWORD'))
        or k == 'LLM_DEEPSEEK_API_KEY'}
    root = a.output.absolute()
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    env.update(ENV_FILE='/dev/null', LOG_DIR=str(root/'logs'),
               AGENT_MODE='false', BACKTEST_ENABLED='false', REPORT_INTEGRITY_RETRY='0',
               MAX_WORKERS='1', LLM_CHANNELS='deepseek', LLM_DEEPSEEK_PROTOCOL='openai',
               LITELLM_MODEL='openai/'+env['LLM_DEEPSEEK_MODELS'], LITELLM_FALLBACK_MODELS='')
    command = [sys.executable, str(Path(__file__).with_name('run_hk_original_model_probe.py')),
               '--checkout', str(a.checkout.resolve()), '--expected-commit', a.expected_commit,
               '--preflight', str(a.preflight.resolve()), '--output', str(root/'native'),
               '--limit-cny', a.limit_cny, '--carry-upper-cny', a.carry_upper_cny]
    with (root/'private-process.log').open('x') as log:
        try:
            result = subprocess.run(command, env=env, stdout=log, stderr=log, timeout=900)
            status = result.returncode
        except subprocess.TimeoutExpired:
            status = 124
    files = {str(f.relative_to(root)): sha(f) for f in root.rglob('*') if f.is_file()}
    # Only this manifest can be shown publicly; contents remain on the private host.
    receipt = {'run_id': a.run_id, 'completed_at': datetime.now(timezone.utc).isoformat(),
               'process_exit': status, 'upstream_commit': a.expected_commit,
               'files': files, 'original_observer_sha256': sha(Path(command[1])),
               'private_raw_persistence': 'LOCAL_ONLY_PENDING_AUTHENTICATED_SAVE',
               'trade_approved': False, 'scope': 'O single-stock; not full-pool ranking'}
    (root/'manifest.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps({'run_id': a.run_id, 'process_exit': status,
                      'manifest_sha256': sha(root/'manifest.json'), 'trade_approved': False}))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
