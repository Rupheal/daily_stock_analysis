"""One single-stock run with before/after balance and persisted output evidence."""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


def balance():
    try:
        response = requests.get(
            os.environ['LLM_DEEPSEEK_BASE_URL'].rstrip('/') + '/user/balance',
            headers={'Authorization': 'Bearer ' + os.environ['LLM_DEEPSEEK_API_KEY']}, timeout=15)
        response.raise_for_status()
        data = response.json()
        return {'time': datetime.now(timezone.utc).isoformat(),
                'is_available':data.get('is_available'), 'balance_infos':data.get('balance_infos')}
    except Exception as exc:
        return {'error_type':type(exc).__name__, 'verified':False}


def main():
    # Preparation must have completed in this same job before exposing a model key.
    if not Path('probe/preflight.json').is_file():
        raise SystemExit('Missing passed preflight evidence')
    before = balance()
    status = None
    try:
        status = subprocess.run([sys.executable,'main.py','--stocks','hk01810',
                                 '--no-notify','--no-market-review','--force-run'],timeout=600).returncode
    finally:
        ledger = {'before':before,'after':balance(), 'process_status':status,
                  'note':'Balance delta is account-wide during the run; other concurrent API use cannot be excluded.'}
        Path('probe/billing.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
        print('BILLING',json.dumps(ledger,ensure_ascii=False),flush=True)
    db = sqlite3.connect(os.getenv('DATABASE_PATH','./data/stock_analysis.db'))
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute('SELECT code,raw_result,context_snapshot,news_content FROM analysis_history ORDER BY id')]
    Path('probe/model-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    for row in rows:
        print('MODEL_RESULT',row['raw_result'],flush=True)
        snapshot = json.loads(row['context_snapshot'] or '{}')
        context = snapshot.get('enhanced_context', snapshot)
        print('MODEL_CONTEXT',json.dumps({key:context.get(key) for key in ('date','today','yesterday','trend_analysis')},ensure_ascii=False),flush=True)
    if status != 0 or len(rows) != 1 or not list(Path('reports').glob('report_*.md')):
        raise SystemExit('Single-stock technical acceptance incomplete; inspect artifacts')
    from src.services.market_data_integrity import audit_daily_report
    audit = audit_daily_report(json.loads(rows[0]['raw_result']), context)
    Path('probe/report-quality-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    print('REPORT_QUALITY',json.dumps(audit,ensure_ascii=False),flush=True)
    if not audit['passed']:
        raise SystemExit('Report quality failed: generated execution plan must not be published as accepted')


if __name__ == '__main__':
    main()
