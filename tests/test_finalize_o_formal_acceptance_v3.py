import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from finalize_o_formal_acceptance_v3 import finalize

def good():
    ranking=[
      {'rank':1,'code':'A','sentiment_score':70,'action':'buy'},
      {'rank':2,'code':'B','sentiment_score':60,'action':'watch'},
      {'rank':3,'code':'C','sentiment_score':55,'action':'watch'},
      {'rank':4,'code':'D','sentiment_score':40,'action':'reduce'},
    ]
    result={
      'run_id':'R','state':'PASS_O_FORMAL_CORE_RANKING_TOP3','target_session':'2026-09-18',
      'official_O_denominator':660,'base_operational_O_denominator':657,
      'missing_count':0,'formal_O_ranking_generated':True,'formal_signal_generated':False,
      'ranking':ranking,'ranking_eligible_count':4,'Top3':ranking[:3],'Top10':ranking,
      'base_excluded_count':3,'additional_excluded_count':653,
      'qualified_buy_in_Top3':1,'real_orders':0,'simulation_writes':0,
      'ranking_contract':{'primary_key':'sentiment_score_desc'},
      'reconciliation':{
        'official_equals_base_plus_excluded':True,
        'processed_plus_missing_equals_base':True,
      }
    }
    policy={'current_session':{'official_denominator':660,'operational_denominator':657}}
    return result,policy

def test_accepts_complete_formal_ranking():
    r,p=good();o=finalize(r,p)
    assert o['status']=='ACCEPTED_O_FORMAL_TOP3'
    assert [x['code'] for x in o['Top3']]==['A','B','C']
    assert o['execution_signal_generated'] is False

def test_missing_blocks():
    r,p=good();r['missing_count']=1
    o=finalize(r,p)
    assert o['status']=='NOT_ACCEPTED'
    assert 'MISSING_OPERATIONAL_MEMBERS' in o['blockers']
    assert o['Top3']==[]

def test_partial_state_blocks():
    r,p=good();r['state']='PARTIAL_O_FORMAL_CORE_PROCESSING'
    assert finalize(r,p)['status']=='NOT_ACCEPTED'

def test_top3_must_equal_ranking_prefix():
    r,p=good();r['Top3']=[r['ranking'][1],r['ranking'][0],r['ranking'][2]]
    o=finalize(r,p)
    assert 'TOP3_NOT_RANKING_PREFIX' in o['blockers']

def test_orders_block():
    r,p=good();r['real_orders']=1
    o=finalize(r,p)
    assert 'ORDER_OR_SIMULATION_SIDE_EFFECT' in o['blockers']

def test_denominator_mismatch_blocks():
    r,p=good();r['base_operational_O_denominator']=656
    o=finalize(r,p)
    assert 'OPERATIONAL_DENOMINATOR_MISMATCH' in o['blockers']
