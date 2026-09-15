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
import inspect
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlparse

from hk_budget_guard import ResearchBudget, decode_usage
from o_native_input_contract import NativeInputContractError, validate_native_input
from o_native_date_boundary_adapter import patched_yahoo_target_boundary
from o_semantic_handoff_contract import (CONTRACT_VERSION, FROZEN_UPSTREAM, ContractError,
    canonical_hash, build_news_handoff, prove_prompt_consumption)
from o_single_output_fact_check import check_saved_output


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit-cny', required=True)
    parser.add_argument('--carry-upper-cny', required=True)
    parser.add_argument('--target-boundary-adapter', action='store_true')
    parser.add_argument('--news-handoff-v1', action='store_true',
        help='Versioned preflight news before native context-pack construction; no implicit request authorization')
    args = parser.parse_args()
    if args.expected_commit != FROZEN_UPSTREAM:
        raise ValueError('SEMANTIC_CONTRACT_REQUIRES_FROZEN_SOURCE')
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

    # The external observer must never pre-load the research fork's ``src`` or
    # ``data_provider`` namespace.  Otherwise Python would reuse those cached
    # modules after the frozen checkout is inserted into sys.path, silently
    # invalidating the claim that the native model logic is original upstream.
    contaminated = sorted(name for name in sys.modules if name == 'src' or name.startswith('src.') or name == 'data_provider' or name.startswith('data_provider.'))
    if contaminated:
        raise RuntimeError('ORIGINAL_NAMESPACE_PRELOADED:' + ','.join(contaminated[:8]))

    os.environ['DATABASE_PATH'] = str(root/'original-data.db')
    os.chdir(checkout)
    sys.path.insert(0, str(checkout))
    import httpx
    from src.analyzer import GeminiAnalyzer
    from main import main as native_main
    from src.core.pipeline import StockAnalysisPipeline
    import src.core.pipeline as native_pipeline_module
    import src.analyzer as native_analyzer_module
    import main as native_main_module
    if not _inside(native_analyzer_module.__file__, checkout) or not _inside(native_main_module.__file__, checkout):
        raise RuntimeError('ORIGINAL_MODULE_ORIGIN_MISMATCH')
    module_origin_receipt = {
        'analyzer_under_frozen_checkout': True,
        'main_under_frozen_checkout': True,
        'analyzer_relative_path': str(Path(native_analyzer_module.__file__).resolve().relative_to(checkout)),
        'main_relative_path': str(Path(native_main_module.__file__).resolve().relative_to(checkout)),
    }

    if not _inside(native_pipeline_module.__file__, checkout):
        raise RuntimeError('ORIGINAL_PIPELINE_ORIGIN_MISMATCH')

    base = os.environ['LLM_DEEPSEEK_BASE_URL']
    model = os.environ['LLM_DEEPSEEK_MODELS']
    budget = ResearchBudget(root/'budget.json', limit=args.limit_cny, carry_upper=args.carry_upper_cny,
                            max_requests=1, model=model, host=urlparse(base).hostname)
    validated = False
    validation_receipt = None
    adapter_applied_count = 0
    news_handoff = None
    prompt_handoff_receipt = None
    output_semantic_receipt = None
    returned_result = None
    observed_input = None
    loader_called = False
    original_format_prompt = GeminiAnalyzer._format_prompt
    original_news_loader = StockAnalysisPipeline._load_persisted_intelligence_context
    original_analyze, original_send = GeminiAnalyzer.analyze, httpx.Client.send
    original_async_send = httpx.AsyncClient.send
    def load_news(instance, *, code, stock_name, market, limit=6):
        nonlocal news_handoff, loader_called
        existing = original_news_loader(instance,code=code,stock_name=stock_name,market=market,limit=limit)
        if not args.news_handoff_v1:
            return existing
        if str(market).lower() != 'hk':
            raise ContractError('PREFLIGHT_NEWS_HK_ONLY')
        window = instance.config.get_effective_news_window_days()
        skeleton = {'code':code,'date':target_session,'today':{'date':target_session},'news_window_days':window}
        news_handoff = build_news_handoff(preflight,skeleton,
            expected_preflight_hash=canonical_hash(preflight),decision_at=started)
        text = news_handoff['news_context']
        if existing not in (None,'',text):
            raise ContractError('EXISTING_NATIVE_NEWS_CONFLICT')
        loader_called = True
        return text or None

    def analyze(instance, context, *a, **kw):
        nonlocal validated, validation_receipt, news_handoff, output_semantic_receipt, returned_result, observed_input
        try:
            validation_receipt = validate_native_input(preflight, context)
        except NativeInputContractError as exc:
            raise ValueError(str(exc)) from None
        bound = inspect.signature(original_analyze).bind(instance,context,*a,**kw)
        observed_input = {'context':context,'news_context':bound.arguments.get('news_context'),
                         'analysis_context_pack_summary':bound.arguments.get('analysis_context_pack_summary'),
                         'capture_stage':'ANALYZER_ENTRY'}
        if args.news_handoff_v1:
            if not loader_called or news_handoff is None:
                raise ContractError('PREFLIGHT_NEWS_LOADER_NOT_CONSUMED')
            verified = build_news_handoff(preflight,context,
                expected_preflight_hash=canonical_hash(preflight),decision_at=started)
            if observed_input['news_context'] != verified['news_context']:
                raise ContractError('PREFLIGHT_NEWS_ARGUMENT_DROPPED_OR_CHANGED')
            if 'news_context_missing' in str(observed_input['analysis_context_pack_summary']):
                raise ContractError('STALE_CONTEXT_PACK_NEWS_MISSING')
            news_handoff = verified
            (root/'news-handoff-receipt.json').write_text(json.dumps(news_handoff,ensure_ascii=False,indent=2))
        validated = True
        (root/'original-input.json').write_text(json.dumps(observed_input,ensure_ascii=False,default=str))
        result = original_analyze(instance, context, *a, **kw)
        returned_result = result
        value = result.to_dict() if hasattr(result,'to_dict') else vars(result)
        (root/'original-result.json').write_text(json.dumps(value,ensure_ascii=False,default=str))
        output_semantic_receipt = check_saved_output(preflight, observed_input, value)
        (root/'output-semantic-receipt.json').write_text(json.dumps(output_semantic_receipt,ensure_ascii=False,indent=2))
        print('ORIGINAL_MODEL_RESULT',json.dumps(value,ensure_ascii=False,default=str),flush=True)
        return result

    def format_prompt(instance, context, name, *a, **kw):
        nonlocal prompt_handoff_receipt
        prompt = original_format_prompt(instance, context, name, *a, **kw)
        if args.news_handoff_v1:
            if news_handoff is None:
                raise ContractError('PREFLIGHT_NEWS_HANDOFF_NOT_PREPARED')
            prompt_handoff_receipt = prove_prompt_consumption(prompt, news_handoff)
            (root/'news-prompt-consumption.json').write_text(json.dumps(prompt_handoff_receipt,indent=2))
        return prompt
    def send(client, request, **kw):
        seq = budget.admit(request, validated and (not args.news_handoff_v1 or bool(prompt_handoff_receipt)))
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
        with patch.object(StockAnalysisPipeline,'_load_persisted_intelligence_context',load_news), patch.object(GeminiAnalyzer,'analyze',analyze), patch.object(GeminiAnalyzer,'_format_prompt',format_prompt), patch.object(httpx.Client,'send',send), patch.object(httpx.AsyncClient,'send',async_send):
            if args.target_boundary_adapter:
                with patched_yahoo_target_boundary(target_session) as applied:
                    status = native_main()
                    adapter_applied_count = applied['count']
            else:
                status = native_main()
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
    finally:
        # The pipeline legitimately finalizes metadata after analyzer return.
        # Record that observed object separately, never rewrite analyzer/provider evidence.
        if returned_result is not None and observed_input is not None:
            final_value = returned_result.to_dict() if hasattr(returned_result,'to_dict') else vars(returned_result)
            (root/'pipeline-final-result.json').write_text(json.dumps(final_value,ensure_ascii=False,default=str))
            output_semantic_receipt = check_saved_output(preflight,observed_input,final_value)
            (root/'pipeline-final-semantic-receipt.json').write_text(json.dumps(output_semantic_receipt,ensure_ascii=False,indent=2))
        report={'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),
                'original_commit':args.expected_commit,'original_tracked_source_unchanged':not subprocess.check_output(['git','diff','--name-only','HEAD'],text=True).strip(),
                'original_module_origins_verified':True,'module_origin_receipt':module_origin_receipt,
                'provider_configuration':'Existing OpenAI-compatible channel configured for authorized DeepSeek',
                'input_validated':validated,'input_validation_receipt':validation_receipt,
                'scope':'O single Xiaomi native analysis; not O660 ranking',
                'preflight_sha256':hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
                'target_boundary_adapter':bool(args.target_boundary_adapter),
                'target_boundary_adapter_scope':'Yahoo retrieval boundary/materialization only' if args.target_boundary_adapter else None,
                'target_boundary_adapter_apply_count':adapter_applied_count,
                'process_status':status,'error':error,'budget':budget.state,'manual_approved':False,
                'news_handoff_version':CONTRACT_VERSION if args.news_handoff_v1 else None,
                'news_handoff_requested':bool(args.news_handoff_v1),'news_loader_consumed':loader_called,
                'news_prompt_consumed':bool(prompt_handoff_receipt),
                'output_semantic_verdict':output_semantic_receipt.get('semantic_verdict') if output_semantic_receipt else 'NOT_REVIEWED',
                'runtime_activated':False,
                'O_denominator':660,'U_denominator':45,'trading_release':'pending_manual_review'}
        (root/'probe-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
        print('ORIGINAL_PROBE_SUMMARY',json.dumps(report,ensure_ascii=False,default=str),flush=True)
    if not budget.state['requests'] or error or output_semantic_receipt is None or output_semantic_receipt.get('semantic_verdict') == 'NO_GO':
        raise SystemExit(1)


if __name__=='__main__':
    main()
