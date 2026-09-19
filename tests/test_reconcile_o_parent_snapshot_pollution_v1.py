import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from reconcile_o_parent_snapshot_pollution_v1 import repair

def fixture():
    ranking=[
      {'rank':1,'code':'A','sentiment_score':59,'action':'hold'},
      {'rank':2,'code':'B','sentiment_score':58,'action':'hold'},
      {'rank':3,'code':'C','sentiment_score':57,'action':'hold'},
    ]
    run075={
      'run_id':'TRI-DSA-O-RECOVER-20260918-075','target_session':'2026-09-18',
      'state':'PARTIAL_O_FORMAL_CORE_PROCESSING',
      'official_O_denominator':15,'base_operational_O_denominator':12,'base_excluded_count':3,
      'ranking_eligible_count':3,'additional_excluded_count':-3,
      'additional_exclusions':[],
      'missing_operational_members':[f'X{i}' for i in range(1,10)],'missing_count':9,
      'shared_unprocessed':[],'shared_unprocessed_count':0,
      'ranking':ranking,'Top3':ranking,'Top10':ranking,
      'formal_O_ranking_generated':False,'formal_signal_generated':False,
      'real_orders':0,'simulation_writes':0,
      'reconciliation':{}
    }
    parent={
      'run_id':'TRI-DSA-O-CONT-20260918-073','missing_count':101,
      'additional_exclusions':[
        {'code':f'X{i}','universe_index':i,'status':'EXCLUDED_PREFLIGHT_NO_RESCUE',
         'failure_code':'TARGET_SESSION_VOLUME_OUTSIDE_CALIBRATED_BOUND'} for i in range(1,10)
      ]
    }
    return run075,parent

def test_repairs_nine_without_changing_ranking():
    r,p=fixture();o=repair(r,p)
    assert o['state']=='PASS_O_FORMAL_CORE_RANKING_TOP3'
    assert o['missing_count']==0
    assert o['processed_operational_members']==12
    assert o['ranking_eligible_count']==3
    assert o['additional_excluded_count']==9
    assert o['Top3']==r['Top3']
    assert o['parent_snapshot_repair']['model_http_requests_added']==0

def test_wrong_parent_failure_code_blocks():
    import pytest
    r,p=fixture();p['additional_exclusions'][0]['failure_code']='OTHER'
    with pytest.raises(ValueError,match='FAILURE_MISMATCH'):
        repair(r,p)

def test_missing_not_in_parent_blocks():
    import pytest
    r,p=fixture();p['additional_exclusions']=p['additional_exclusions'][1:]
    with pytest.raises(ValueError,match='MISSING_NOT_IN_AUTHORITATIVE_PARENT'):
        repair(r,p)
