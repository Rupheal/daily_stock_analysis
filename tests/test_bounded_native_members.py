"""Risk-path tests: paid subprocess never starts after preflight/claim failures."""
import sys,json,hashlib,os
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_hk_bounded_native_members as runner
from datetime import date
from types import SimpleNamespace


def setup(monkeypatch,tmp_path):
    cache=tmp_path/'cache.json';cache.write_text('{}');scope=tmp_path/'scope.json';scope.write_text(json.dumps({'maximum_requests':2,'codes':['00700','01024'],'maximum_cost_cny':'0.20','per_member_cap_cny':'0.10','history_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'target_session':'2026-09-16','artifact_prefix':'TEST-RUN034','run_id':'TEST-RUN034','frozen_upstream':'089d9d26d68f8b839ea5a74a3784e4402925f8b7'}))
    out=tmp_path/'out';monkeypatch.setattr(sys,'argv',['x','--checkout',str(tmp_path),'--cache',str(cache),'--scope',str(scope),'--out',str(out)])
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_EVENT_NAME','push');monkeypatch.setenv('GITHUB_RUN_ID','1');monkeypatch.setenv('DSA_DEEPSEEK_V41_TOKENIZER','test');monkeypatch.setenv('DEEPSEEK_API_KEY','unit-secret');monkeypatch.setenv('DSA_DRIVE_FOLDER_ID','unit-folder')
    import o_target_session_contract
    monkeypatch.setattr(o_target_session_contract,'resolve_target_session',lambda _:SimpleNamespace(target_session=date(2026,9,16)))
    monkeypatch.setattr(runner,'private_save',lambda *args:{'save_read_hash_restore':True,'sha256':'a'*64,'bytes':1})
    return out


def test_preflight_failure_is_not_a_free_pass_to_model(monkeypatch,tmp_path):
    out=setup(monkeypatch,tmp_path);calls=[]
    def command(script,args,env,log):
        calls.append(script.name);assert 'DEEPSEEK_API_KEY' not in env;return 1
    monkeypatch.setattr(runner,'command',command);monkeypatch.setattr(runner,'balance',lambda:pytest.fail('Balance/claim should not be reached'))
    runner.main();r=json.loads((out/'SANITIZED_RESULT.json').read_text())
    assert calls==['prepare_hk_member_acceptance.py']*2 and r['model_http_requests_possible']==0 and len(r['members'])==2


def test_claim_failure_prevents_paid_subprocess_and_preserves_receipt(monkeypatch,tmp_path):
    out=setup(monkeypatch,tmp_path);calls=[]
    def command(script,args,env,log):
        calls.append((script.name,env.get('DSA_BUDGET_PROBE_ONLY')))
        if script.name.startswith('prepare'):
            p=Path(args[args.index('--out')+1]);p.mkdir();(p/'preflight.json').write_text('{}')
        else:
            assert env['DSA_BUDGET_PROBE_ONLY']=='1'
            p=Path(args[args.index('--output')+1]);p.mkdir();(p/'budget.json').write_text(json.dumps({'requests':[{'status':'dry_envelope_validated_not_sent','pre_send_peak_upper_cny':'0.08'}]}))
        return 0
    monkeypatch.setattr(runner,'command',command);monkeypatch.setattr(runner,'balance',lambda:runner.Decimal('1'))
    class LocalClient:
        def __init__(self,**kwargs):self.headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(runner.httpx,'Client',LocalClient)
    monkeypatch.setattr(runner,'scoped_token',lambda _: 'fake-private-token')
    monkeypatch.setattr(runner.DriveStore,'reserve_native_call',lambda *a:(_ for _ in ()).throw(ValueError('CLAIM_EXISTS_RECONCILE_NO_REPEAT_MODEL')))
    runner.main();r=json.loads((out/'SANITIZED_RESULT.json').read_text())
    assert all(mode in (None,'1') for _,mode in calls) and r['model_http_requests_possible']==0
    assert all('CLAIM_EXISTS' in m['failure_code'] for m in r['members'])


def test_pre_send_storage_failure_stops_before_balance_or_claim(monkeypatch,tmp_path):
    out=setup(monkeypatch,tmp_path)
    def command(script,args,env,log):
        if script.name.startswith('prepare'):
            p=Path(args[args.index('--out')+1]);p.mkdir();(p/'preflight.json').write_text('{}')
        else:
            assert env['DSA_BUDGET_PROBE_ONLY']=='1'
            p=Path(args[args.index('--output')+1]);p.mkdir();(p/'budget.json').write_text(json.dumps({'requests':[{'status':'dry_envelope_validated_not_sent','pre_send_peak_upper_cny':'0.08'}]}))
        return 0
    monkeypatch.setattr(runner,'command',command)
    monkeypatch.setattr(runner,'private_save',lambda *a:(_ for _ in ()).throw(runner.StoreError('BUNDLE_TOO_LARGE')))
    monkeypatch.setattr(runner,'balance',lambda:pytest.fail('No billing/claim after private storage failure'))
    runner.main();r=json.loads((out/'SANITIZED_RESULT.json').read_text())
    assert r['model_http_requests_possible']==0 and r['members'][0]['private_persistence']['reason']=='BUNDLE_TOO_LARGE'
    assert r['members'][1]['status']=='ISOLATED_AFTER_PRIVATE_OR_SHARED_FAILURE'
