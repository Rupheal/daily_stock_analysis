"""One native DSA run; one model HTTP request, raw usage and balance evidence."""
import json
import hashlib
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
    fundamental = context.get('fundamental_context') or {}
    if any((fundamental.get(key) or {}).get('data') for key in ('earnings', 'growth', 'valuation')):
        raise ValueError('Unverified HK financial data reached model input')
    if 'realtime_quote' in json.dumps(fundamental.get('source_chain') or [], ensure_ascii=False):
        raise ValueError('Quarantined financial source chain reached model input')


def validate_preflight_artifacts(root):
    queue = json.loads((root/'acceptance-queue.json').read_text())
    expected = {'prices': 'passed', 'news': 'passed_limited_coverage',
                'issuer': 'listing_passed_body_incomplete', 'manifest': 'passed'}
    if 'primary_evidence' in queue.get('tasks', {}):
        expected['primary_evidence'] = 'passed'
    if queue.get('tasks') != expected or not queue.get('manifest'):
        raise ValueError('Free acceptance queue incomplete')
    for name, digest in queue['manifest'].items():
        if Path(name).name != name or hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Preflight evidence hash mismatch: ' + name)
    return queue


def run_constrained():
    """Reuse the accepted data, HTTP guard and fact renderer for bounded U research."""
    from src.services.hk_evidence_analysis import build_evidence_input, model_messages, render_research_brief
    from src.reports.xiaomi_fact_brief import render_html, render_markdown
    root = Path('probe')
    validate_preflight_artifacts(root)
    if os.getenv('GITHUB_ACTIONS') and (os.getenv('GITHUB_RUN_ATTEMPT') != '1' or os.getenv('GITHUB_EVENT_NAME') != 'push'):
        raise RuntimeError('Reruns and implicit retries are outside this request slot')
    checkpoint = json.loads(Path('docs/xiaomi-acceptance-checkpoint.json').read_text())
    budget = checkpoint['next_model_budget']
    previous = checkpoint['billing']['research_goal_batch']
    if budget['authorization_status'] != 'ACCEPTED_USER_GOAL' or budget['batch_id'] != previous['batch_id'] or budget['remaining_http_requests'] <= 0:
        raise RuntimeError('No remaining accepted batch authorization')
    preflight = json.loads((root/'preflight.json').read_text())
    payload = build_evidence_input(preflight)
    guard = SingleCallGuard(os.environ['LLM_DEEPSEEK_BASE_URL'], os.environ['LLM_DEEPSEEK_MODELS'],
        reservation_path=root/'model-request-reservation.json', prior_calls=previous['actual_http_requests'],
        prior_reserved_cny=previous['reserved_cny'], max_calls=budget['max_requests'])
    body = {'model': guard.model, 'messages': model_messages(payload), 'stream': False,
        'max_tokens': 8192, 'response_format': {'type': 'json_object'}}
    (root/'actual-model-input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    before = balance()
    failure = None
    try:
        with httpx.Client(timeout=120, transport=httpx.HTTPTransport(retries=0), follow_redirects=False) as client:
            request = client.build_request('POST', os.environ['LLM_DEEPSEEK_BASE_URL'].rstrip('/')+'/chat/completions',
                headers={'Authorization': 'Bearer '+os.environ['LLM_DEEPSEEK_API_KEY']}, json=body)
            guard.input_validated = True
            guard.admit(request)  # Durable exclusive reservation before network I/O.
            response = client.send(request)
            guard.capture(response)
            response.raise_for_status()
        choice = guard.raw_response['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('Incomplete model response')
        judgments = json.loads(choice['message']['content'])
        brief = render_research_brief(preflight, payload, judgments)
        (root/'constrained-judgments.json').write_text(json.dumps(judgments,ensure_ascii=False,indent=2))
        (root/'constrained-research.json').write_text(json.dumps(brief,ensure_ascii=False,indent=2))
        (root/'constrained-research.md').write_text(render_markdown(brief))
        (root/'constrained-research.html').write_text(render_html(brief))
        print('CONSTRAINED_JUDGMENTS',json.dumps(judgments,ensure_ascii=False),flush=True)
        print('CONSTRAINED_AUDIT',json.dumps(brief['model_audit'],ensure_ascii=False),flush=True)
    except Exception as exc:
        failure = type(exc).__name__
        raise
    finally:
        after = balance()
        usage = guard.raw_usage or {}
        # Peak price is a conservative upper estimate for this pinned pricing
        # review; the exact invoice and rounded account balance are separate.
        estimate = None
        if 'prompt_tokens' in usage and 'completion_tokens' in usage:
            estimate = str((Decimal(usage['prompt_tokens'])*2 + Decimal(usage['completion_tokens'])*8)/1000000)
        ledger = {'batch_id': budget['batch_id'], 'model_http_requests': guard.sent,
            'reserved_cny': str(guard.reserved_cny), 'prior_calls': guard.prior_calls,
            'cumulative_reserved_cny': str(guard.prior_reserved_cny+guard.reserved_cny),
            'raw_provider_usage': guard.raw_usage, 'response_model': guard.response_model,
            'estimated_upper_cost_cny': estimate, 'actual_cost_cny': None,
            'pricing_url': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
            'pricing_checked_date': '2026-09-12', 'estimate_basis': 'Flash peak price, all input cache misses; CNY2/8 per million input/output; reasoning included in completion',
            'before': before, 'after': after, 'failure_type': failure,
            'history_note': 'This new batch does not reset any historical project costs.'}
        (root/'billing.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
        print('BILLING',json.dumps(ledger,ensure_ascii=False),flush=True)
        if guard.raw_response is not None:
            (root/'provider-response.json').write_text(json.dumps(guard.raw_response,ensure_ascii=False,indent=2))
            print('PROVIDER_RESPONSE',json.dumps(guard.raw_response,ensure_ascii=False),flush=True)


def record_report_review(result, context, enforce, output_dir):
    """Retain the real failed output even when the pipeline correctly skips history."""
    before = json.loads(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
    before['raw_response'] = getattr(result, 'raw_response', None)
    before['data_sources'] = getattr(result, 'data_sources', before.get('data_sources', ''))
    audit = enforce(result, context)
    review = {'before_enforcement': before, 'audit': audit,
              'after_enforcement': result.to_dict()}
    (output_dir/'report-review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2, default=str))
    print('REPORT_REVIEW', json.dumps(review, ensure_ascii=False, default=str), flush=True)
    return audit


class SingleCallGuard:
    def __init__(self, base_url, model, *, reservation_path=None, prior_calls=0, prior_reserved_cny=0, max_calls=2):
        self.host = urlsplit(base_url).hostname
        self.model = model
        self.sent = 0
        self.input_validated = False
        self.raw_usage = None
        self.response_model = None
        self.raw_response = None
        self.reservation_path = Path(reservation_path) if reservation_path else None
        self.prior_calls = prior_calls
        self.max_calls = max_calls
        self.prior_reserved_cny = Decimal(str(prior_reserved_cny))
        self.reserved_cny = Decimal('0')

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
        # Conservative reservation: 150k input tokens (above the 100k UTF-8 byte
        # envelope), all cache misses at peak price, plus the full 8192 output cap.
        # This is a spending estimate, not a provider invoice or tokenizer proof.
        reserve = Decimal('0.40')
        if self.prior_calls >= self.max_calls or self.prior_reserved_cny + reserve > Decimal('1.20'):
            raise RuntimeError('User approval required: request count or CNY budget exceeded')
        if self.reservation_path:
            self.reservation_path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation before the network request; failures consume the slot.
            with self.reservation_path.open('x') as handle:
                json.dump({'reserved_at': datetime.now(timezone.utc).isoformat(),
                    'run_id': os.getenv('GITHUB_RUN_ID'), 'commit': os.getenv('GITHUB_SHA'),
                    'prior_calls': self.prior_calls, 'max_authorized_calls': self.max_calls,
                    'reserved_cny': str(reserve),
                    'cumulative_reserved_cny': str(self.prior_reserved_cny + reserve),
                    'status': 'reserved_before_send; no automatic refund'}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        self.reserved_cny = reserve
        self.sent += 1
        return True

    def capture(self, response):
        try:
            data = response.json()
            self.raw_response = data
            self.raw_usage = data.get('usage')
            self.response_model = data.get('model')
        except (ValueError, RuntimeError):
            pass


def main():
    validate_preflight_artifacts(Path('probe'))
    preflight = json.loads(Path('probe/preflight.json').read_text())
    from src.analyzer import GeminiAnalyzer
    from src.services.market_data_integrity import audit_daily_report
    from src.services import market_data_integrity
    from main import main as dsa_main
    if os.getenv('GITHUB_ACTIONS') and (os.getenv('GITHUB_RUN_ATTEMPT') != '1'
                                      or os.getenv('GITHUB_EVENT_NAME') != 'push'):
        raise RuntimeError('This budget authorization excludes workflow reruns and dispatches')
    guard = SingleCallGuard(os.environ['LLM_DEEPSEEK_BASE_URL'], os.environ['LLM_DEEPSEEK_MODELS'],
        reservation_path='probe/model-request-reservation.json',
        prior_calls=int(os.getenv('ACCEPTANCE_PRIOR_CALLS', '0')),
        prior_reserved_cny=os.getenv('ACCEPTANCE_PRIOR_RESERVED_CNY', '0'),
        max_calls=int(os.getenv('ACCEPTANCE_MAX_CALLS', '2')))
    original_analyze = GeminiAnalyzer.analyze
    original_impl = GeminiAnalyzer._call_litellm_impl
    original_dispatch = GeminiAnalyzer._dispatch_litellm_completion
    original_send, original_async_send = httpx.Client.send, httpx.AsyncClient.send
    original_enforce = market_data_integrity.enforce_daily_report

    def enforce(result, context):
        return record_report_review(result, context, original_enforce, Path('probe'))

    def analyze(instance, context, *args, **kwargs):
        from src.services.hk_report_contract import attach_report_contract
        context['company_news_evidence'] = preflight['company_news_evidence']
        attach_report_contract(context)
        validate_model_input(context, preflight)
        if context.get('hk_report_contract') != preflight.get('hk_report_contract'):
            raise ValueError('Reviewed evidence changed after free preflight')
        context['issuer_announcements'] = preflight['issuer_announcements']
        guard.input_validated = True
        Path('probe/actual-model-input.json').write_text(json.dumps(context, ensure_ascii=False, default=str))
        print('MODEL_INPUT_GUARD', json.dumps({'passed': True, 'date': str(context['today']['date']),
            'financial_blocks_empty': True,
            'financial_policy': (context.get('fundamental_context') or {}).get('financial_evidence_policy')},
            ensure_ascii=False), flush=True)
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
        ), patch.object(httpx.AsyncClient, 'send', async_send), patch.object(
            market_data_integrity, 'enforce_daily_report', enforce):
            status = dsa_main()
    finally:
        sys.argv = original_argv
        after = balance()
        ledger = {'before': before, 'after': after, 'process_status': status,
            'model_http_requests': guard.sent, 'response_model': guard.response_model,
            'raw_provider_usage': guard.raw_usage, 'balance_delta': None,
            'reserved_cny': str(guard.reserved_cny), 'prior_calls': guard.prior_calls,
            'max_authorized_calls': guard.max_calls,
            'cumulative_reserved_cny': str(guard.prior_reserved_cny + guard.reserved_cny),
            'target_budget_cny': '1.00', 'approval_threshold_cny': '1.20',
            'note': 'Balance delta is account-wide; token prices/rounding and concurrent use can differ.'}
        try:
            b = {r['currency']: Decimal(r['total_balance']) for r in before['balance_infos']}
            a = {r['currency']: Decimal(r['total_balance']) for r in after['balance_infos']}
            ledger['balance_delta'] = {currency: str(b[currency]-a[currency]) for currency in b.keys() & a.keys()}
        except (KeyError, TypeError, ArithmeticError):
            pass
        Path('probe/billing.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
        print('BILLING', json.dumps(ledger, ensure_ascii=False), flush=True)
        if guard.raw_response is not None:
            Path('probe/provider-response.json').write_text(json.dumps(guard.raw_response, ensure_ascii=False, indent=2))
            print('PROVIDER_RESPONSE', json.dumps(guard.raw_response, ensure_ascii=False), flush=True)
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
    if '--constrained' in sys.argv:
        run_constrained()
    else:
        main()
