import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    'lag_detector', ROOT/'scripts/dashboard_feed_lag_detector_v019.py'
)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def receipt(run_id='RUN060', session='2026-09-18', o_ready=657, u_ready=45):
    return {
        'run_id': run_id,
        'source_workflow_run': 1,
        'source_artifact_digest': 'sha256:abc',
        'target_session': session,
        'official_O_denominator': 660,
        'official_U_denominator': 45,
        'U_buy_eligible': 44,
        'O_current_valid': o_ready,
        'O_current_invalid': [] if o_ready==660 else [
            {'code': 'X'} for _ in range(660-o_ready)
        ],
        'U_current_valid': u_ready,
        'model_http_requests': 0,
        'DeepSeek_API_cost_cny': 0,
        'formal_signal_generated': False,
    }


def feed_for(receipt_path, authority_root, r):
    sha=hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    return {
        'meta': {'schema_version':'0.19','generated_at':'2026-09-18T13:18:00Z','source_commit':'x'},
        'authority': {
            'source_receipt': str(receipt_path.relative_to(authority_root)).replace('\\','/'),
            'source_receipt_sha256': sha,
            'evidence_session': r['target_session'],
            'source_run_id': r['run_id'],
            'strategy_acceptance': 'NONE_FORMAL_SIGNAL_GENERATED_FALSE',
        },
        'O': {'denominator':660,'data_ready':r['O_current_valid'],'data_isolated':660-r['O_current_valid']},
        'U': {'denominator':45,'data_ready':r['U_current_valid'],'data_isolated':45-r['U_current_valid'],'buy_eligible':44},
        'budget': {'actual_request_count':0,'cost':0},
    }


def test_aligned(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    p=auth/'docs/runtime/RUN060_RECOVERED_RESULT.json'
    r=receipt('TRI-RUN060','2026-09-18')
    write_json(p,r)
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',feed_for(p,auth,r))
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==0
    assert report['status']=='ALIGNED'


def test_source_ahead_by_session(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    p60=auth/'docs/runtime/RUN060_RECOVERED_RESULT.json'
    r60=receipt('TRI-RUN060','2026-09-18')
    write_json(p60,r60)
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',feed_for(p60,auth,r60))
    p61=auth/'docs/runtime/RUN061_RESULT.json'
    write_json(p61,receipt('TRI-RUN061','2026-09-21',660,45))
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==2
    assert report['status']=='SOURCE_AHEAD'
    assert report['latest_authority']['run_id']=='TRI-RUN061'


def test_source_ahead_by_run_number_same_session(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    p60=auth/'docs/runtime/RUN060_RESULT.json'
    r60=receipt('TRI-RUN060','2026-09-18')
    write_json(p60,r60)
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',feed_for(p60,auth,r60))
    p61=auth/'docs/runtime/RUN061_RESULT.json'
    write_json(p61,receipt('TRI-RUN061','2026-09-18',659,45))
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==2
    assert report['latest_authority']['receipt'].endswith('RUN061_RESULT.json')


def test_hash_mismatch(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    p=auth/'docs/runtime/RUN060_RESULT.json'
    r=receipt('TRI-RUN060','2026-09-18')
    write_json(p,r)
    f=feed_for(p,auth,r)
    f['authority']['source_receipt_sha256']='0'*64
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',f)
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==3
    assert report['status']=='SOURCE_MISMATCH'
    assert 'source_receipt_sha256' in report['mismatches']


def test_metric_mismatch(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    p=auth/'docs/runtime/RUN060_RESULT.json'
    r=receipt('TRI-RUN060','2026-09-18')
    write_json(p,r)
    f=feed_for(p,auth,r)
    f['O']['data_ready']=656
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',f)
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==3
    assert 'O.data_ready' in report['mismatches']


def test_authority_unavailable(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',{'meta':{'schema_version':'0.19'},'authority':{}})
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==4
    assert report['status']=='AUTHORITY_UNAVAILABLE'


def test_invalid_feed(tmp_path):
    dash=tmp_path/'dash'; auth=tmp_path/'auth'
    (dash).mkdir(parents=True)
    (dash/'DSA_DASHBOARD_LIVE_V019.json').write_text('{bad',encoding='utf-8')
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==5
    assert report['status']=='FEED_INVALID'


def test_checked_in_feed_declares_authority_pointer():
    feed=json.loads((ROOT/'DSA_DASHBOARD_LIVE_V019.json').read_text(encoding='utf-8'))
    assert feed['meta']['schema_version']=='0.19'
    assert feed['authority']['source_receipt'].startswith('docs/runtime/RUN')
    assert len(feed['authority']['source_receipt_sha256'])==64
    assert feed['authority']['evidence_session']


def test_overlay_hash_mismatch(tmp_path):
    dash=tmp_path/'dash';auth=tmp_path/'auth'
    p=auth/'docs/runtime/RUN060_RESULT.json';r=receipt('TRI-RUN060','2026-09-18')
    write_json(p,r)
    f=feed_for(p,auth,r)
    f['authority']['overlay_sha256']={'O_formal':'0'*64,'U_formal':None,'production_runtime':None}
    write_json(auth/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',{'target_session':'2026-09-18'})
    write_json(dash/'DSA_DASHBOARD_LIVE_V019.json',f)
    report,code=mod.detect(dash,auth,'DSA_DASHBOARD_LIVE_V019.json')
    assert code==3
    assert 'authority.overlay_sha256' in report['mismatches']
