"""One authentic original-DSA analysis with an external budget/data observer.

Original source, prompts, scoring and response remain unchanged. Outputs are
diagnostics pending manual review, not approved full-pool rankings.  For the
explicitly authorized Run018 recovery, the wrapper may apply the bounded Yahoo
target-session retrieval adapter outside the frozen upstream checkout.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlparse

from hk_budget_guard import ResearchBudget, decode_usage
from o_native_input_contract import NativeInputContractError, validate_native_input
from o_native_date_boundary_adapter import patched_yahoo_target_boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit-cny', required=True)
    parser.add_argument('--carry-upper-cny', required=True)
    parser.add_argument('--target-boundary-adapter', action='store_true')
    args = parser.parse_args()
    checkout, root, preflight_path = args.checkout.resolve(), args.output.resolve(), args.preflight.resolve()
    if os.getenv('GITHUB_ACTIONS') and (os.getenv('GITHUB_RUN_ATTEMPT') != '1' or os.getenv('GITHUB_EVENT_NAME') != 'push'):
        raise RuntimeError('This concrete request slot is not reusable')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip() != args.expected_commit:
        raise ValueError('Original commit mismatch')
    if subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=checkout,text=True).strip():
        raise ValueError('Original tracked source must remain unchanged')
    root.mkdir(parents=True, exist_ok=False)
    preflight = json.loads(preflight_path.read_text())
    if preflight.get('passed') is not True or preflight.get('symbol', '').upper() != 'HK01810':
        raise ValueError('A passed Xiaomi preflight is required')
    target_session = str(preflight.get('target') or '')
    if args.target_boundary_adapter and not target_session:
        raise ValueError('Target-session adapter requires a frozen preflight target')
    os.environ['DATABASE_PATH'] = str(root/'original-data.db')
    os.chdir(checkout)
    sys.path.insert(0, str(checkout))
    import httpx
    from src.analyzer import GeminiAnalyzer
    from main import main as native_main
    base = os.environ['LLM_DEEPSEEK_BASE_URL']
    model = os.environ['LLM_DEEPSEEK_MODELS']
    budget = ResearchBudget(root/'budget.json', limit=args.limit_cny, carry_upper=args.carry_upper_cny,
                            max_requests=1, model=model, host=urlparse(base).hostname)
    validated = False
    validation_receipt = None
    adapter_applied_count = 0
    original_analyze, original_send = GeminiAnalyzer.analyze, httpx.Client.send
    original_async_send = httpx.AsyncClient.send
    def analyze(instance, context, *a, **kw):
        nonlocal validated, validation_receipt
        try:
            validation_receipt = validate_native_input(preflight, context)
        except NativeInputContractError as exc:
            raise ValueError(str(exc)) from None
        validated = True
        (root/'original-input.json').write_text(json.dumps({'context':context,'news_context':kw.get('news_context',a[0] if a else None)},ensure_ascii=False,default=str))
        result = original_analyze(instance, context, *a, **kw)
        value = result.to_dict() if hasattr(result,'to_dict') else vars(result)
        (root/'original-result.json').write_text(json.dumps(value,ensure_ascii=False,default=str))
        print('ORIGINAL_MODEL_RESULT',json.dumps(value,ensure_ascii=False,default=str),flush=True)
        return result
    def send(client, request, **kw):
        seq = budget.admit(request, validated)
        response = original_send(client, request, **kw)
        if seq:
            raw = response.read().decode('utf-8')
            (root/'provider-response.txt').write_text(raw)
            (root/'request-body.json').write_bytes(request.content)
            budget.settle(seq, decode_usage(raw), 'response_received' if response.status_code==200 else 'http_error')
        return response
    async def async_send(client, request, **kw):
        if request.url.host == urlparse(base).hostname or request.url.path.endswith('/chat/completions'):
            raise RuntimeError('Unexpected async model route; no request sent')
        return await original_async_send(client,request,**kw)
    started = datetime.now(timezone.utc).isoformat()
    status, error = None, None
    try:
        sys.argv=['main.py','--stocks','hk01810','--no-notify','--no-market-review','--force-run','--workers','1']
        with patch.object(GeminiAnalyzer,'analyze',analyze), patch.object(httpx.Client,'send',send), patch.object(httpx.AsyncClient,'send',async_send):
            if args.target_boundary_adapter:
                with patched_yahoo_target_boundary(target_session) as applied:
                    status = native_main()
                    adapter_applied_count = applied['count']
            else:
                status = native_main()
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
    finally:
        report={'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),
                'original_commit':args.expected_commit,'original_tracked_source_unchanged':not subprocess.check_output(['git','diff','--name-only','HEAD'],text=True).strip(),
                'provider_configuration':'Existing OpenAI-compatible channel configured for authorized DeepSeek',
                'input_validated':validated,'input_validation_receipt':validation_receipt,
                'scope':'O single Xiaomi native analysis; not O660 ranking',
                'preflight_sha256':hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
                'target_boundary_adapter':bool(args.target_boundary_adapter),
                'target_boundary_adapter_scope':'Yahoo retrieval boundary/materialization only' if args.target_boundary_adapter else None,
                'target_boundary_adapter_apply_count':adapter_applied_count,
                'process_status':status,'error':error,'budget':budget.state,'manual_approved':False,
                'O_denominator':660,'U_denominator':45,'trading_release':'pending_manual_review'}
        (root/'probe-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
        print('ORIGINAL_PROBE_SUMMARY',json.dumps(report,ensure_ascii=False,default=str),flush=True)
    if not budget.state['requests'] or error:
        raise SystemExit(1)


if __name__=='__main__':
    main()
