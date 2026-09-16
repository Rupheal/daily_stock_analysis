"""Model-free namespace regression required by the CHILD2 workflow.

No source selection, provider call, private journal write or authorization change.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import types

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import run_hk_original_model_probe as probe


def test_external_observer_and_probe_import_do_not_load_research_src():
    program="import sys;sys.path.insert(0,sys.argv[1]);import o_native_input_contract;import run_hk_original_model_probe;bad=[n for n in sys.modules if n=='src' or n.startswith('src.') or n=='data_provider' or n.startswith('data_provider.')];assert not bad,bad"
    env={k:v for k,v in os.environ.items() if not k.startswith('LLM_') and 'DEEPSEEK' not in k}
    result=subprocess.run([sys.executable,'-c',program,str(SCRIPTS)],capture_output=True,text=True,timeout=20,env=env)
    assert result.returncode==0,result.stderr


def test_inside_accepts_only_actual_checkout_descendant(tmp_path):
    root=tmp_path/'original';inside=root/'src'/'analyzer.py';inside.parent.mkdir(parents=True);inside.write_text('# synthetic')
    outside=tmp_path/'original_other'/'src.py';outside.parent.mkdir();outside.write_text('# synthetic')
    assert probe._inside(inside,root)
    assert not probe._inside(outside,root)
    assert not probe._inside(root/'..'/'original_other'/'src.py',root)


def test_symlink_outside_frozen_checkout_is_not_original(tmp_path):
    root=tmp_path/'original';root.mkdir();outside=tmp_path/'research.py';outside.write_text('# synthetic')
    link=root/'analyzer.py';link.symlink_to(outside)
    assert not probe._inside(link,root)


def test_contaminated_namespace_is_rejected_before_provider_configuration(tmp_path,monkeypatch):
    checkout=tmp_path/'original';checkout.mkdir()
    preflight=tmp_path/'preflight.json';preflight.write_text(json.dumps({'passed':True,'symbol':'HK01810','target':'2026-09-15'}))
    output=tmp_path/'output'
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.delenv('LLM_DEEPSEEK_BASE_URL',raising=False)
    monkeypatch.delenv('LLM_DEEPSEEK_MODELS',raising=False)
    monkeypatch.setitem(sys.modules,'src',types.ModuleType('src'))
    def git_only(argv,**kwargs):
        assert argv[0]=='git'
        return probe.FROZEN_UPSTREAM+'\n' if argv[1]=='rev-parse' else ''
    monkeypatch.setattr(probe.subprocess,'check_output',git_only)
    monkeypatch.setattr(sys,'argv',['probe','--checkout',str(checkout),'--expected-commit',probe.FROZEN_UPSTREAM,'--preflight',str(preflight),'--output',str(output),'--limit-cny','2','--carry-upper-cny','0'])
    try:
        probe.main()
    except RuntimeError as exc:
        assert str(exc).startswith('ORIGINAL_NAMESPACE_PRELOADED:')
    else:
        raise AssertionError('Contaminated namespace unexpectedly accepted')
    assert not (output/'request-body.json').exists()
    assert not (output/'provider-response.txt').exists()
    assert not (output/'budget.json').exists()
