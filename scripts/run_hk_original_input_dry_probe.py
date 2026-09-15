"""Model-free dry probe of the true frozen original DSA analyzer input.

The script stops at the original GeminiAnalyzer.analyze boundary, validates the
same accepted preflight contract, records only sanitized input metadata, and
never calls any model endpoint.  It exists solely to prove module origin and
input routing before consuming the still-unused Run018 provider request slot.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlparse

from o_native_input_contract import NativeInputContractError, validate_native_input
from o_native_date_boundary_adapter import patched_yahoo_target_boundary


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve()); return True
    except Exception:
        return False


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkout',type=Path,required=True)
    p.add_argument('--expected-commit',required=True)
    p.add_argument('--preflight',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--target-boundary-adapter',action='store_true')
    a=p.parse_args()
    checkout=a.checkout.resolve(); output=a.output.resolve(); preflight_path=a.preflight.resolve()
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()==a.expected_commit
    assert not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=checkout,text=True).strip()
    preflight=json.loads(preflight_path.read_text()); target=str(preflight.get('target') or '')
    polluted=sorted(n for n in sys.modules if n=='src' or n.startswith('src.') or n=='data_provider' or n.startswith('data_provider.'))
    if polluted: raise RuntimeError('ORIGINAL_NAMESPACE_PRELOADED:'+','.join(polluted[:8]))
    output.mkdir(parents=True,exist_ok=False); os.environ['DATABASE_PATH']=str(output/'dry-original-data.db')
    os.chdir(checkout); sys.path.insert(0,str(checkout))
    import httpx
    from src.analyzer import GeminiAnalyzer
    from main import main as native_main
    import src.analyzer as analyzer_module, main as main_module
    if not _inside(analyzer_module.__file__,checkout) or not _inside(main_module.__file__,checkout): raise RuntimeError('ORIGINAL_MODULE_ORIGIN_MISMATCH')
    captured={}
    original_send=httpx.Client.send; original_async=httpx.AsyncClient.send
    def analyze(instance,context,*args,**kwargs):
        try: receipt=validate_native_input(preflight,context)
        except NativeInputContractError as exc: raise ValueError(str(exc)) from None
        captured.update({
            'reached_original_analyzer':True,
            'input_validated':True,
            'target':receipt['target'],
            'volume_status':receipt['volume_status'],
            'news_context_present':bool(kwargs.get('news_context',args[0] if args else None)),
            'context_news_evidence_present':context.get('news_evidence_present'),
            'context_date':str((context.get('today') or {}).get('date'))[:10],
        })
        raise RuntimeError('RUN018_DRY_STOP_BEFORE_PROVIDER')
    def send(client,request,**kwargs):
        if request.url.path.endswith('/chat/completions'): raise RuntimeError('MODEL_HTTP_FORBIDDEN_IN_DRY_PROBE')
        return original_send(client,request,**kwargs)
    async def async_send(client,request,**kwargs):
        if request.url.path.endswith('/chat/completions'): raise RuntimeError('MODEL_HTTP_FORBIDDEN_IN_DRY_PROBE')
        return await original_async(client,request,**kwargs)
    sys.argv=['main.py','--stocks','hk01810','--no-notify','--no-market-review','--force-run','--workers','1']
    with patch.object(GeminiAnalyzer,'analyze',analyze),patch.object(httpx.Client,'send',send),patch.object(httpx.AsyncClient,'send',async_send):
        if a.target_boundary_adapter:
            with patched_yahoo_target_boundary(target) as applied:
                status=native_main(); captured['target_boundary_adapter_apply_count']=applied['count']
        else: status=native_main(); captured['target_boundary_adapter_apply_count']=0
    captured.update({
        'native_main_status':status,
        'model_http_requests':0,
        'original_commit':a.expected_commit,
        'original_tracked_source_unchanged':not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=checkout,text=True).strip(),
        'analyzer_under_frozen_checkout':_inside(analyzer_module.__file__,checkout),
        'main_under_frozen_checkout':_inside(main_module.__file__,checkout),
    })
    (output/'dry-input-receipt.json').write_text(json.dumps(captured,indent=2,sort_keys=True))
    print(json.dumps(captured,sort_keys=True))
    if not captured.get('reached_original_analyzer') or not captured.get('input_validated'): raise SystemExit(1)

if __name__=='__main__': main()
