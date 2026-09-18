import importlib.util
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    'sync_bridge', ROOT/'scripts/dashboard_sync_bridge_v019.py'
)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def copy_runtime_scripts(dst):
    (dst/'scripts').mkdir(parents=True,exist_ok=True)
    for name in [
        'dashboard_feed_generator_v019.py',
        'dashboard_feed_lag_detector_v019.py',
    ]:
        shutil.copy2(ROOT/'scripts'/name,dst/'scripts'/name)


def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def receipt(run_id,session,o_ready=657,u_ready=45):
    return {
        'schema_version':1,
        'run_id':run_id,
        'source_workflow_run':123,
        'source_artifact_digest':'sha256:abc',
        'target_session':session,
        'decision_session':session,
        'state':'CORE_DATA_REFRESH_PASS',
        'official_O_denominator':660,
        'official_U_denominator':45,
        'U_buy_eligible':44,
        'O_current_valid':o_ready,
        'O_current_invalid':[{'code':str(i)} for i in range(660-o_ready)],
        'U_current_valid':u_ready,
        'model_http_requests':0,
        'DeepSeek_API_cost_cny':0,
        'real_orders':0,
        'simulation_writes':0,
        'formal_signal_generated':False,
        'next':'zero-model sentinel',
    }


def seed_dashboard(dash):
    copy_runtime_scripts(dash)
    write_json(dash/'DSA_DASHBOARD_HISTORY_V019.json',{
        'schema_version':'0.19','append_only':True,'days':[]
    })


def test_first_sync_updates_and_aligns(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'; seed_dashboard(dash)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21',659,45))
    r=mod.sync(dash,auth,'AUTH-SHA-61',generated_at='2026-09-21T09:00:00Z')
    assert r['status']=='UPDATED_ALIGNED'
    assert r['changed'] is True
    f=json.load(open(dash/'DSA_DASHBOARD_LIVE_V019.json'))
    assert f['authority']['authority_commit']=='AUTH-SHA-61'
    assert f['authority']['authority_branch']=='fix/native-private-execution-20260914'
    assert f['O']['data_ready']==659
    assert f['O']['accepted']==0
    assert f['U']['data_ready']==45
    assert f['U']['accepted']==0


def test_second_sync_same_receipt_is_noop(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'; seed_dashboard(dash)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21'))
    one=mod.sync(dash,auth,'AUTH-SHA-61',generated_at='2026-09-21T09:00:00Z')
    before=(dash/'DSA_DASHBOARD_LIVE_V019.json').read_bytes()
    two=mod.sync(dash,auth,'AUTH-SHA-61B',generated_at='2026-09-21T10:00:00Z')
    after=(dash/'DSA_DASHBOARD_LIVE_V019.json').read_bytes()
    assert one['changed'] is True
    assert two['status']=='NOOP_ALREADY_ALIGNED'
    assert two['changed'] is False
    assert before==after


def test_newer_same_day_run_updates_feed_without_replacing_history_day(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'; seed_dashboard(dash)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21',657,45))
    mod.sync(dash,auth,'SHA61',generated_at='2026-09-21T09:00:00Z')
    write_json(auth/'docs/runtime/RUN062_RESULT.json',receipt('TRI-RUN062','2026-09-21',660,45))
    r=mod.sync(dash,auth,'SHA62',generated_at='2026-09-21T10:00:00Z')
    f=json.load(open(dash/'DSA_DASHBOARD_LIVE_V019.json'))
    h=json.load(open(dash/'DSA_DASHBOARD_HISTORY_V019.json'))
    assert r['status']=='UPDATED_ALIGNED'
    assert f['authority']['source_run_id']=='TRI-RUN062'
    assert f['O']['data_ready']==660
    assert len(h['days'])==1
    assert h['days'][0]['date']=='2026-09-21'


def test_new_session_appends_history(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'; seed_dashboard(dash)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21'))
    mod.sync(dash,auth,'SHA61',generated_at='2026-09-21T09:00:00Z')
    write_json(auth/'docs/runtime/RUN062_RESULT.json',receipt('TRI-RUN062','2026-09-22'))
    mod.sync(dash,auth,'SHA62',generated_at='2026-09-22T09:00:00Z')
    h=json.load(open(dash/'DSA_DASHBOARD_HISTORY_V019.json'))
    assert [x['date'] for x in h['days']]==['2026-09-21','2026-09-22']


def test_bridge_preserves_no_formal_signal_boundary(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'; seed_dashboard(dash)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21'))
    mod.sync(dash,auth,'SHA61',generated_at='2026-09-21T09:00:00Z')
    f=json.load(open(dash/'DSA_DASHBOARD_LIVE_V019.json'))
    assert f['authority']['strategy_acceptance']=='NONE_FORMAL_SIGNAL_GENERATED_FALSE'
    assert f['simulation']['eligibility']=='WAIT_NOT_ELIGIBLE_NO_FORMAL_SIGNAL'
    assert f['O']['qualified_buy'] is False
    assert f['U']['qualified_buy'] is False
