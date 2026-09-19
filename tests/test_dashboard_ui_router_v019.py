import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ui_router',ROOT/'scripts/dashboard_ui_router_v019.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def receipt(run_id,session,o_ready=657):
    return {
        'run_id':run_id,
        'source_workflow_run':1,
        'source_artifact_digest':'sha256:abc',
        'target_session':session,
        'official_O_denominator':660,
        'official_U_denominator':45,
        'U_buy_eligible':44,
        'O_current_valid':o_ready,
        'O_current_invalid':[{'code':str(i)} for i in range(660-o_ready)],
        'U_current_valid':45,
        'model_http_requests':0,
        'DeepSeek_API_cost_cny':0,
        'formal_signal_generated':False,
    }


def seed(dash,auth,with_v019=True,with_v018=True):
    (dash/'scripts').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'scripts/dashboard_feed_lag_detector_v019.py',dash/'scripts/dashboard_feed_lag_detector_v019.py')
    (dash/mod.V019_UI).write_text('v019',encoding='utf-8')
    (dash/mod.V018_UI).write_text('v018',encoding='utf-8')
    if with_v019:
        write_json(dash/mod.V019_ACCEPT,{'status':'ACCEPTED_ENGINEERING'})
    if with_v018:
        write_json(dash/mod.V018_ACCEPT,{'status':'ACCEPTED_ENGINEERING'})
    p=auth/'docs/runtime/RUN060_RESULT.json'
    r=receipt('TRI-RUN060','2026-09-18')
    write_json(p,r)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    write_json(dash/mod.V019_FEED,{
        'meta':{'schema_version':'0.19','generated_at':'2026-09-18T12:00:00Z','source_commit':'x'},
        'authority':{
            'source_receipt':'docs/runtime/RUN060_RESULT.json',
            'source_receipt_sha256':sha,
            'source_run_id':'TRI-RUN060',
            'evidence_session':'2026-09-18',
            'strategy_acceptance':'NONE_FORMAL_SIGNAL_GENERATED_FALSE',
            'overlay_sha256':{'O_formal':None,'U_formal':None,'production_runtime':None},
        },
        'O':{'denominator':660,'data_ready':657,'data_isolated':3},
        'U':{'denominator':45,'data_ready':45,'data_isolated':0,'buy_eligible':44},
        'budget':{'actual_request_count':0,'cost':0},
    })


def test_aligned_routes_v019(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth)
    r,code=mod.resolve(dash,auth)
    assert code==0
    assert r['selected_version']=='v0.19'
    assert r['route_state']=='CURRENT_AUTHORITY_ALIGNED'
    assert r['fallback'] is False
    assert r['badge']=='CURRENT / READ ONLY'


def test_source_ahead_falls_back_v018(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth)
    write_json(auth/'docs/runtime/RUN061_RESULT.json',receipt('TRI-RUN061','2026-09-21',660))
    r,code=mod.resolve(dash,auth)
    assert code==10
    assert r['selected_version']=='v0.18'
    assert r['route_state']=='LAST_VALIDATED_FALLBACK'
    assert r['fallback'] is True
    assert r['fallback_reason']=='SOURCE_AHEAD'
    assert 'LAST VALIDATED' in r['badge']


def test_feed_mismatch_falls_back_v018(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth)
    f=json.load(open(dash/mod.V019_FEED))
    f['O']['data_ready']=656
    write_json(dash/mod.V019_FEED,f)
    r,code=mod.resolve(dash,auth)
    assert code==10
    assert r['selected_version']=='v0.18'
    assert r['fallback_reason']=='SOURCE_MISMATCH'


def test_v019_not_accepted_falls_back_v018(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth,with_v019=False)
    r,code=mod.resolve(dash,auth)
    assert code==10
    assert r['selected_version']=='v0.18'
    assert r['fallback_reason']=='V019_NOT_ENGINEERING_ACCEPTED'


def test_no_safe_ui_blocks(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth,with_v019=False,with_v018=False)
    r,code=mod.resolve(dash,auth)
    assert code==20
    assert r['route_state']=='NO_SAFE_UI'
    assert r['selected_version'] is None
    assert r['badge']=='BLOCKED'


def test_command_is_exact_and_read_only(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth';seed(dash,auth)
    r,code=mod.resolve(dash,auth)
    assert code==0
    assert r['command']=='/tri dsa ui'
    assert r['read_only'] is True
    assert 'research/dsa-dashboard-v019-20260918' in r['selected_url']
