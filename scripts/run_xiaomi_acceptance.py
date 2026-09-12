"""One native DSA run; one model HTTP request, raw usage and balance evidence."""
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import requests


def balance():
    try:
        response = requests.get(
            os.environ['LLM_DEEPSEEK_BASE_URL'].rstrip('/') + '/user/balance',
            headers={'Authorization': 'Bearer ' + os.environ['LLM_DEEPSEEK_API_KEY']}, timeout=15)
        response.raise_for_status()
        data = response.json()
        return {'time': datetime.now(timezone.utc).isoformat(),
                'is_available': data.get('is_available'), 'balance_infos': data.get('balance_infos')}
    except Exception as exc:
        return {'error_type': type(exc).__name__, 'verified': False}


def validate_model_input(context, preflight):
    if not preflight.get('passed'):
        raise ValueError('Preflight did not pass')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(preflight['prepared_at'])
    if not timedelta(0) <= age <= timedelta(hours=1):
        raise ValueError('Preflight expired')
    if str(context['today']['date'])[:10] != preflight['target']:
        raise ValueError('Model input session changed')
    for key in ('open', 'high', 'low', 'close', 'volume', 'ma5', 'ma10', 'ma20', 'volume_ratio'):
        actual, expected = float(context['today'][key]), float(preflight['today'][key])
        if not math.isfinite(actual) or abs(actual-expected) > (0 if key == 'volume' else 0.015):
            raise ValueError('Model input differs from accepted evidence: ' + key)


class SingleCallGuard:
    def __init__(self, base_url, model):
        self.host = urlsplit(base_url).hostname
        self.model = model
        self.sent = 0
        self.input_validated = False
        self.raw_usage = None
        self.response_model = None

    def admit(self, request):
        if request.method != 'POST' or not request.url.path.endswith('/chat/completions'):
            return False
        if not self.input_validated or request.url.host != self.host or self.sent:
            raise RuntimeError('Single-call acceptance guard blocked model request')
        body = json.loads(request.content)
        if body.get('model') != self.model or body.get('stream'):
            raise RuntimeError('Unexpected model route or streaming request')
        if len(request.content) > 100000 or not 0 < int(body.get('max_tokens', 0)) <= 8192:
            raise RuntimeError('Model request exceeds acceptance size limit')
        self.sent += 1
        return True

    def capture(self, response):
        try:
            data = response.json()
            self.raw_usage = data.get('usage')
            self.response_model = data.get('model')
        except (ValueError, RuntimeError):
            pass


def main():
    preflight = json.loads(Path('probe/preflight.json').read_text())
    from src.analyzer import GeminiAnalyzer
    from src.services.market_data_integrity import audit_daily_report
    from main import main as dsa_main
    guard = SingleCallGuard(os.environ['LLM_DEEPSEEK_BASE_URL'], os.environ['LLM_DEEPSEEK_MODELS'])
    original_analyze = GeminiAnalyzer.analyze
    original_impl = GeminiAnalyzer._call_litellm_impl
    original_dispatch = GeminiAnalyzer._dispatch_litellm_completion
    original_send, original_async_send = httpx.Client.send, httpx.AsyncClient.send

    def analyze(instance, context, *args, **kwargs):
        validate_model_input(context, preflight)
        guard.input_validated = True
        Path('probe/actual-model-input.json').write_text(json.dumps(context, ensure_ascii=False, default=str))
        return original_analyze(instance, context, *args, **kwargs)

    def generate(instance, *args, **kwargs):
        kwargs['stream'] = False
        return original_impl(instance, *args, **kwargs)

    def dispatch(instance, model, call_kwargs, **kwargs):
        effective = dict(call_kwargs, stream=False, num_retries=0, max_tokens=8192)
        if instance._router:
            instance._router.num_retries = 0
        return original_dispatch(instance, model, effective, **kwargs)

    def send(client, request, **kwargs):
        model_request = guard.admit(request)
        response = original_send(client, request, **kwargs)
        if model_request:
            response.read()
            guard.capture(response)
        return response

    async def async_send(client, request, **kwargs):
        model_request = guard.admit(request)
        response = await original_async_send(client, request, **kwargs)
        if model_request:
            await response.aread()
            guard.capture(response)
        return response

    before, status = balance(), None
    original_argv = sys.argv
    try:
        sys.argv = ['main.py', '--stocks', 'hk01810', '--no-notify', '--no-market-review', '--force-run']
        with patch.object(GeminiAnalyzer, 'analyze', analyze), patch.object(
            GeminiAnalyzer, '_call_litellm_impl', generate
        ), patch.object(GeminiAnalyzer, '_dispatch_litellm_completion', dispatch), patch.object(
            httpx.Client, 'send', send
        ), patch.object(httpx.AsyncClient, 'send', async_send):
            status = dsa_main()
    finally:
        sys.argv = original_argv
        after = balance()
        ledger = {'before': before, 'after': after, 'process_status': status,
            'model_http_requests': guard.sent, 'response_model': guard.response_model,
            'raw_provider_usage': guard.raw_usage, 'balance_delta': None,
            'note': 'Balance delta is account-wide; token prices/rounding and concurrent use can differ.'}
        try:
            b = {r['currency']: Decimal(r['total_balance']) for r in before['balance_infos']}
            a = {r['currency']: Decimal(r['total_balance']) for r in after['balance_infos']}
            ledger['balance_delta'] = {currency: str(b[currency]-a[currency]) for currency in b.keys() & a.keys()}
        except (KeyError, TypeError, ArithmeticError):
            pass
        Path('probe/billing.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
        print('BILLING', json.dumps(ledger, ensure_ascii=False), flush=True)
    db = sqlite3.connect(os.getenv('DATABASE_PATH', './data/stock_analysis.db'))
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute(
        'SELECT code,raw_result,context_snapshot,news_content FROM analysis_history ORDER BY id')]
    db.close()
    Path('probe/model-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    if len(rows) != 1:
        raise SystemExit('Expected exactly one native DSA result')
    result = json.loads(rows[0]['raw_result'])
    context = json.loads(Path('probe/actual-model-input.json').read_text())
    audit = audit_daily_report(result, context)
    audit['native_success'] = result.get('success')
    audit['model_http_requests'] = guard.sent
    audit['passed'] = bool(audit['passed'] and result.get('success') and guard.sent == 1 and status == 0)
    Path('probe/report-quality-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print('MODEL_RESULT', json.dumps(result, ensure_ascii=False), flush=True)
    print('REPORT_QUALITY', json.dumps(audit, ensure_ascii=False), flush=True)
    if not audit['passed']:
        raise SystemExit('Report acceptance failed; execution plan remains unapproved')


if __name__ == '__main__':
    main()
