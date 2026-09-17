import hashlib,json,sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_hk_bounded_native_members as runner

def test_pool_target_v2_preflight_route_is_free_and_uses_plan(monkeypatch,tmp_path):
    cache=tmp_path/'cache.json';cache.write_text('{}')
    scope=tmp_path/'scope.json';scope.write_text(json.dumps({
      'maximum_requests':1,'codes':['00001'],'maximum_cost_cny':'0.10','per_member_cap_cny':'0.10',
      'history_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'target_session':'2026-09-17',
      'artifact_prefix':'TEST-RUN058E','run_id':'TEST-RUN058E','frozen_upstream':'089d9d26d68f8b839ea5a74a3784e4402925f8b7',
      'preflight_contract':'POOL_TARGET_V2','preflight_plan':'docs/runtime/RUN057_O_NATIVE_PLAN.json'}))
    out=tmp_path/'out'
    monkeypatch.setattr(sys,'argv',['x','--checkout',str(tmp_path),'--cache',str(cache),'--scope',str(scope),'--out',str(out)])
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_EVENT_NAME','push');monkeypatch.setenv('GITHUB_RUN_ID','1');monkeypatch.setenv('DSA_DEEPSEEK_V41_TOKENIZER','test')
    import o_target_session_contract
    monkeypatch.setattr(o_target_session_contract,'resolve_target_session',lambda _:SimpleNamespace(target_session=date(2026,9,17)))
    monkeypatch.setattr(runner,'private_save',lambda *args:{'save_read_hash_restore':True,'sha256':'a'*64,'bytes':1})
    calls=[]
    def command(script,args,env,log):
        calls.append((script.name,args,list(env)))
        assert 'DEEPSEEK_API_KEY' not in env
        return 1
    monkeypatch.setattr(runner,'command',command)
    monkeypatch.setattr(runner,'balance',lambda:pytest.fail('balance must not be reached after free preflight failure'))
    runner.main()
    assert calls[0][0]=='prepare_hk_pool_rollout_preflight_v2.py'
    assert '--plan' in calls[0][1]
    assert calls[0][1][calls[0][1].index('--plan')+1].endswith('docs/runtime/RUN057_O_NATIVE_PLAN.json')
    result=json.loads((out/'SANITIZED_RESULT.json').read_text())
    assert result['model_http_requests_possible']==0
