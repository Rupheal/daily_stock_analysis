"""Generate a no-model Xiaomi fact brief from fresh data or an explicit snapshot."""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reports.xiaomi_fact_brief import build_fact_brief, render_html, render_markdown


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--refresh', action='store_true', help='Fetch and cross-check the latest complete session')
    source.add_argument('--preflight', type=Path, help='Replay a saved JSON snapshot; never labelled fresh')
    parser.add_argument('--output-dir', type=Path, default=Path('reports/xiaomi-facts'))
    args = parser.parse_args(argv)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root = args.output_dir / run_id
    root.mkdir(parents=True, exist_ok=False)
    expected = None
    try:
        if args.refresh:
            from scripts.prepare_xiaomi_acceptance import prepare
            from src.core.trading_calendar import get_effective_trading_date
            audit = prepare(root / 'evidence', allow_partial_news=True)
            expected = str(get_effective_trading_date('hk'))
        else:
            audit = json.loads(args.preflight.read_text(encoding='utf-8'))
            write_json(root / 'preflight-snapshot.json', audit)
        brief = build_fact_brief(audit, mode='refresh' if args.refresh else 'snapshot', expected_date=expected)
        write_json(root / 'xiaomi-facts.json', brief)
        (root / 'xiaomi-facts.md').write_text(render_markdown(brief), encoding='utf-8')
        (root / 'xiaomi-facts.html').write_text(render_html(brief), encoding='utf-8')
        manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.rglob('*')) if p.is_file()}
        write_json(root / 'manifest.json', {'run_id': run_id, 'commit': os.getenv('GITHUB_SHA'),
            'model_http_requests': 0, 'files': manifest, 'status': brief['status']})
        print('FACT_BRIEF', json.dumps(brief, ensure_ascii=False))
        print('FACT_BRIEF_OUTPUT', str(root))
        return 0
    except Exception as exc:
        failure = {'run_id': run_id, 'status': 'NO_REPORT', 'model_http_requests': 0,
                   'error': type(exc).__name__ + ': ' + str(exc)}
        write_json(root / 'failure.json', failure)
        print('FACT_BRIEF_FAILURE', json.dumps(failure, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
