import copy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from o_strategy_core_acceptance import evaluate

def case():
    p={
      'target':'2026-09-18','news_count':0,'risk_review_complete':False,
      'execution_contract':{'version':'O_GATE_A_EXECUTION_CONTRACT_v2','target_session':'2026-09-18','realtime_quote_available':False},
    }
    i={'context':{'date':'2026-09-18','today':{'date':'2026-09-18','open':10,'close':10,'volume':100},'yesterday':{'date':'2026-09-17','close':10.2,'volume':90}},'news_context':None}
    r={'action':'buy','decision_type':'buy','sentiment_score':68,'operation_advice':'买入','current_price':None,'search_performed':False,
       'news_result_count_known':False,'news_result_count':None,'analysis_summary':'新闻数据有限，需继续核验风险'}
    return p,i,r

def test_clean_core_accepted():
    p,i,r=case();o=evaluate(p,i,r)
    assert o['status']=='CORE_ACCEPTED'
    assert o['ranking_eligible'] is True
    assert o['strategy_core']['sentiment_score']==68
    assert o['strategy_core']['action']=='buy'
    assert o['narrative_release_status']=='PASS'

def test_sem002_narrative_is_quarantined_not_core_rejected():
    p,i,r=case();r['analysis_summary']='未见近3日重大利空公告'
    o=evaluate(p,i,r)
    assert o['status']=='CORE_ACCEPTED'
    assert o['ranking_eligible'] is True
    assert o['narrative_release_status']=='QUARANTINED'
    assert 'SEM-002' in o['semantic_guards']
    assert not o['core_semantic_findings']

def test_sem001_dashboard_price_is_quarantined_not_core_rejected():
    p,i,r=case();r['dashboard']={'data_perspective':{'price_position':{'current_price':10}}}
    o=evaluate(p,i,r)
    assert o['status']=='CORE_ACCEPTED'
    assert o['narrative_release_status']=='QUARANTINED'
    assert 'SEM-001' in o['semantic_guards']

def test_opening_contradiction_is_hard_reject():
    p,i,r=case();r['pattern_analysis']='今日高开后走强'
    o=evaluate(p,i,r)
    assert o['status']=='CORE_REJECTED'
    assert 'HARD_SEMANTIC_BLOCK' in o['blockers']

def test_score_action_conflict_requires_guardrail():
    p,i,r=case();r.update(sentiment_score=75,action='watch',decision_type='hold')
    o=evaluate(p,i,r)
    assert o['status']=='CORE_REJECTED'
    assert 'SCORE_ACTION_CONFLICT_WITHOUT_GUARDRAIL' in o['blockers']
    r['guardrail_reason']='风险门控降级'
    o=evaluate(p,i,r)
    assert o['status']=='CORE_ACCEPTED'
    assert o['strategy_core']['guardrail_reason_present'] is True

def test_decision_type_conflict_rejected():
    p,i,r=case();r['decision_type']='sell'
    o=evaluate(p,i,r)
    assert o['status']=='CORE_REJECTED'
    assert 'ACTION_DECISION_TYPE_CONFLICT' in o['blockers']

def test_bad_score_rejected():
    p,i,r=case();r['sentiment_score']=101
    o=evaluate(p,i,r)
    assert o['status']=='CORE_REJECTED'
    assert 'INVALID_SENTIMENT_SCORE' in o['blockers']

def test_raw_result_never_mutated():
    p,i,r=case();r['analysis_summary']='未见重大利空';before=copy.deepcopy(r)
    evaluate(p,i,r)
    assert r==before
