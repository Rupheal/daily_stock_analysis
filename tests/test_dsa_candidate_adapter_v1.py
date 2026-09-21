import json,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import dsa_candidate_adapter_v1 as ca

TARGET='2026-09-18'

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2))
    return path

def o_wait():
    return {'status':'ACCEPTED_O_FORMAL_TOP3','target_session':TARGET,'official_O_denominator':660,'operational_O_denominator':657,'ranking_eligible_count':356,'base_excluded_count':3,'additional_excluded_count':301,'missing_count':0,'qualified_buy_in_Top3':0,'Top3':[{'code':'00148','rank':1,'sentiment_score':59,'action':'hold','action_family':'hold'},{'code':'00177','rank':2,'sentiment_score':59,'action':'hold','action_family':'hold'},{'code':'00552','rank':3,'sentiment_score':59,'action':'hold','action_family':'hold'}]}

def u_blocked():
    return {'state':'PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED','target_session':TARGET,'denominator':45,'formal_valid_rows':0,'qualified_BUY':0,'Top3':[],'rows':[]}

def setup_case(tmp_path):
    scripts=tmp_path/'scripts'; scripts.mkdir()
    scripts.joinpath('dsa_production_orchestrator_v1.py').write_text((ROOT/'scripts/dsa_production_orchestrator_v1.py').read_text())
    write(tmp_path/'o.json',o_wait()); write(tmp_path/'u.json',u_blocked())
    write(tmp_path/'acceptance.json',{'status':'ACCEPTED_ENGINEERING','current_route':{'target_session':TARGET,'O':{'receipt_session':TARGET},'U':{'receipt_session':'2026-09-17'}}})
    write(tmp_path/'journal.json',{'state':'JOURNAL_INITIALIZED','command_count':0,'journal_hash':'j'*64,'config_hash':'c'*64,'real_orders':0})
    def spec(name):
        data=(tmp_path/name).read_bytes()
        return {'path':name,'git_blob_sha1':ca._git_blob_sha1(data)}
    pointer={'authority':'NONE_READ_ONLY_SNAPSHOT','target_session':TARGET,'foundation_source':{'task_id':'T','run_id':'R'},'sources':{
      'O':{**spec('o.json'),'expected_acceptance':'ACCEPTED_O_FORMAL_TOP3','official_denominator':660,'operational_denominator':657},
      'U':{**spec('u.json'),'expected_state_prefix':'PASS_FORMAL_U_DECISION','denominator':45},
      'orchestrator_module':spec('scripts/dsa_production_orchestrator_v1.py'),
      'orchestrator_acceptance':spec('acceptance.json'),
      'simulation_journal_readiness':spec('journal.json')}}
    write(tmp_path/'pointer.json',pointer)
    sys.modules.pop('dsa_production_orchestrator_v1',None)
    return pointer

def test_current_case_matches_orchestrator_and_is_deterministic(tmp_path):
    setup_case(tmp_path)
    a=ca.run_adapter(tmp_path,tmp_path/'pointer.json')
    sys.modules.pop('dsa_production_orchestrator_v1',None)
    b=ca.run_adapter(tmp_path,tmp_path/'pointer.json')
    assert a==b
    assert a['tracks']['O']['state']=='WAIT'
    assert a['tracks']['U']['state']=='BLOCKED'
    assert a['comparison']['O']['match'] and a['comparison']['U']['match']
    assert a['parallel_shadow_status']=='PASS_WITH_MISMATCH_INVENTORY'
    assert a['mismatch_inventory'][0]['code']=='PRODUCTION_SNAPSHOT_U_RECEIPT_SESSION_STALE'
    assert a['side_effects']['new_buy_created']==0

def test_hash_drift_fails_closed(tmp_path):
    setup_case(tmp_path)
    p=json.loads((tmp_path/'o.json').read_text());p['missing_count']=1;write(tmp_path/'o.json',p)
    with pytest.raises(ca.CandidateAdapterError,match='HASH_DRIFT_O_RECEIPT'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')

def test_missing_receipt_fails_closed(tmp_path):
    setup_case(tmp_path); (tmp_path/'u.json').unlink()
    with pytest.raises(ca.CandidateAdapterError,match='MISSING_U_RECEIPT'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')

def test_authority_conflict_fails_closed(tmp_path):
    pointer=setup_case(tmp_path)
    u=json.loads((tmp_path/'u.json').read_text());u['target_session']='2026-09-17';write(tmp_path/'u.json',u)
    pointer['sources']['U']['git_blob_sha1']=ca._git_blob_sha1((tmp_path/'u.json').read_bytes());write(tmp_path/'pointer.json',pointer)
    with pytest.raises(ca.CandidateAdapterError,match='AUTHORITY_CONFLICT_SESSION'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')

def test_denominator_mismatch_fails_closed(tmp_path):
    pointer=setup_case(tmp_path)
    o=json.loads((tmp_path/'o.json').read_text());o['ranking_eligible_count']=355;write(tmp_path/'o.json',o)
    pointer['sources']['O']['git_blob_sha1']=ca._git_blob_sha1((tmp_path/'o.json').read_bytes());write(tmp_path/'pointer.json',pointer)
    with pytest.raises(ca.CandidateAdapterError,match='DENOMINATOR_EQUATION_O'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')

def test_acceptance_state_fails_closed(tmp_path):
    pointer=setup_case(tmp_path)
    o=json.loads((tmp_path/'o.json').read_text());o['status']='DRAFT';write(tmp_path/'o.json',o)
    pointer['sources']['O']['git_blob_sha1']=ca._git_blob_sha1((tmp_path/'o.json').read_bytes());write(tmp_path/'pointer.json',pointer)
    with pytest.raises(ca.CandidateAdapterError,match='ACCEPTANCE_STATE_O'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')

def test_no_source_mutation(tmp_path):
    setup_case(tmp_path)
    before={n:(tmp_path/n).read_bytes() for n in ('o.json','u.json','acceptance.json','journal.json')}
    ca.run_adapter(tmp_path,tmp_path/'pointer.json')
    after={n:(tmp_path/n).read_bytes() for n in before}
    assert before==after

def test_second_authority_ledger_forbidden(tmp_path):
    pointer=setup_case(tmp_path);pointer['authority']='CANDIDATE_AUTHORITY';write(tmp_path/'pointer.json',pointer)
    with pytest.raises(ca.CandidateAdapterError,match='SECOND_AUTHORITY_LEDGER_FORBIDDEN'):
        ca.run_adapter(tmp_path,tmp_path/'pointer.json')
