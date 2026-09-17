"""Run025 contracts: synthetic cases only, no provider call."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from o_post_output_contract import *


def base_case():
    p={'symbol':'HK01810','target':'2026-01-05','news_count':0}
    i={'context':{'code':'HK01810','date':'2026-01-05',
       'today':{'date':'2026-01-05','open':'10.0'},'yesterday':{'close':'10.2'}},'news_context':None}
    r={'success':True,'error_message':None,'pattern_analysis':'低开，开盘低于前收','action':'watch',
       'news_result_count_known':True,'news_result_count':None,'current_price':None,'search_performed':False}
    return p,i,r


def source():
    return {'frozen_upstream':FROZEN_UPSTREAM,'pipeline_sha256':PINNED_SHA256['pipeline'],
            'observer_sha256':'a'*64,'pipeline_module_under_checkout':True}


def evaluated(p,i,r,**kw):
    a=deepcopy(r)
    c=build_final_capture(p,i,a,r,source_proof=source(),input_version='FROZEN_NATIVE_INPUT_NO_HANDOFF_v1')
    return evaluate_post_output_contract(p,i,r,capture_receipt=c,analyzer_result=a,expected_sources=source(),**kw)


def test_open_gap_is_shared_and_deterministic():
    p,i,r=base_case()
    for price,direction in [('10.0','GAP_DOWN'),('10.3','GAP_UP'),('10.2','FLAT_OPEN')]:
        i['context']['today']['open']=price
        assert derive_open_gap(i)['direction']==direction


@pytest.mark.parametrize('success',[False,None,'true',1])
def test_failed_or_unproven_native_default_cannot_be_accepted(success):
    p,i,r=base_case();r.update(success=success,operation_advice='持有',sentiment_score=50)
    out=evaluated(p,i,r)
    assert 'NATIVE_ANALYSIS_SUCCESS_NOT_PROVEN' in out['promotion_gate']['blockers']
    assert out['promotion_gate']['status']=='BLOCK'


def test_success_flag_does_not_hide_error_message():
    p,i,r=base_case();r['error_message']='synthetic provider failure'
    assert 'NATIVE_ANALYSIS_ERROR_PRESENT' in evaluated(p,i,r)['promotion_gate']['blockers']


@pytest.mark.parametrize('bad',[None,True,'NaN','Infinity',0,-1])
def test_open_nonfinite_or_nonpositive_block(bad):
    p,i,r=base_case();i['context']['today']['open']=bad
    assert evaluated(p,i,r)['promotion_gate']['status']=='BLOCK'


@pytest.mark.parametrize('value,state',[(None,'NOT_SEARCHED'),(0,'SEARCHED_ZERO'),(4,'SEARCHED_HITS')])
def test_final_native_tristate_not_numeric_known(value,state):
    p,i,r=base_case();r['news_result_count']=value
    out=evaluated(p,i,r)
    assert out['deterministic_facts']['news_result_count']['final_search_state']==state
    assert out['promotion_gate']['status']=='PASS'
    assert not out['promotion_gate']['o_single_stock_formal_acceptance']


@pytest.mark.parametrize('bad',[True,False,-1,1.5,'2',{},[]])
def test_invalid_native_count_still_blocks(bad):
    p,i,r=base_case();r['news_result_count']=bad
    assert validate_news_count_contract(r)['status']=='BLOCK'


def test_missing_known_field_and_nonboolean_flag():
    assert validate_news_count_contract({'news_result_count_known':True})['status']=='BLOCK'
    assert validate_news_count_contract({'news_result_count_known':'true','news_result_count':0})['status']=='BLOCK'
    assert validate_news_count_contract({})['native_state']['state']=='LEGACY_UNKNOWN'


@pytest.mark.parametrize('value',[None,0,4])
def test_early_count_always_unknown(value):
    p,i,r=base_case();r['news_result_count']=value
    out=evaluate_post_output_contract(p,i,r,capture_receipt={'stage':EARLY_STAGE})
    assert out['deterministic_facts']['news_result_count']['final_search_state']=='UNKNOWN_AT_CAPTURE_STAGE'
    assert not out['deterministic_facts']['news_result_count']['numeric_count_known']
    assert out['promotion_gate']['status']=='BLOCK'
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' not in out['promotion_gate']['blockers']


@pytest.mark.parametrize('bad',[None,True,-1,1.5,'2'])
def test_independent_numeric_count_requires_integer(bad):
    assert validate_numeric_count_sidecar({'version':NUMERIC_COUNT_VERSION,'numeric_count_known':True,'numeric_count':bad})['status']=='BLOCK'


def test_numeric_sidecar_zero_is_not_not_searched():
    p,i,r=base_case()
    out=evaluated(p,i,r,numeric_sidecar={'version':NUMERIC_COUNT_VERSION,'numeric_count_known':True,'numeric_count':0})
    assert 'NUMERIC_COUNT_SIDECAR_STATE_MISMATCH' in out['promotion_gate']['blockers']
    r['news_result_count']=0
    assert evaluated(p,i,r,numeric_sidecar={'version':NUMERIC_COUNT_VERSION,'numeric_count_known':True,'numeric_count':0})['semantic_contract_pass']


@pytest.mark.parametrize('guard,field,value',[
    ('SEM-001','dashboard',{'data_perspective':{'price_position':{'current_price':10.1}}}),
    ('SEM-002','checklist','未见近3日利空公告'),
    ('SEM-003','sector_position','公司是恒生科技指数权重股之一'),
])
def test_sem_only_blocks_formal_exit(guard,field,value):
    p,i,r=base_case();r[field]=value;out=evaluated(p,i,r)
    assert not [f for f in out['semantic_audit']['findings'] if f['severity']=='BLOCK']
    assert out['formal_semantic_gates'][guard]=='BLOCK'
    assert output_exit_code(out,request_count=1)==1


def test_correct_unknown_disclosure_is_positive_control():
    p,i,r=base_case();r['disclosure']='实时行情缺失，仅使用上一交易日收盘价；无法排查近3日重大利空'
    out=evaluated(p,i,r)
    assert out['semantic_contract_pass'] and output_exit_code(out,request_count=1)==0
    assert not out['promotion_gate']['o_single_stock_formal_acceptance']


@pytest.mark.parametrize('text',['昨天高开','若明日高开则等待','不是高开，而是低开'])
def test_history_hypothesis_negation_not_misclassified(text):
    p,i,r=base_case();r['pattern_analysis']=text
    assert evaluated(p,i,r)['promotion_gate']['status']=='PASS'


def test_current_opening_contradiction_blocks():
    p,i,r=base_case();r['pattern_analysis']='高开，开盘高于前收'
    assert 'OPEN_GAP_DIRECTION_CONTRADICTION' in evaluated(p,i,r)['promotion_gate']['blockers']


@pytest.mark.parametrize('field', ['stage','target_session','symbol','final_result_sha256','analyzer_result_sha256','input_sha256','preflight_sha256','input_version','source_proof'])
def test_stage_identity_and_hash_tampering_fails(field):
    p,i,r=base_case();c=build_final_capture(p,i,r,r,source_proof=source(),input_version='FROZEN_NATIVE_INPUT_NO_HANDOFF_v1')
    c[field]=None
    out=evaluate_post_output_contract(p,i,r,capture_receipt=c,analyzer_result=r,expected_sources=source())
    assert not out['capture_verified'] and output_exit_code(out,request_count=1)==1


def test_preflight_only_news_blocks():
    p,i,r=base_case();p['news_count']=4
    assert 'PREFLIGHT_NEWS_NOT_DELIVERED_TO_NATIVE_INPUT' in evaluated(p,i,r)['promotion_gate']['blockers']


def test_guard_and_sources_are_immutable_and_deterministic():
    p,i,r=base_case();before=deepcopy((p,i,r))
    assert evaluated(p,i,r)==evaluated(p,i,r) and (p,i,r)==before


@pytest.mark.parametrize('count,error,status',[(0,None,0),(2,None,0),(True,None,0),(1,'failure',0),(1,None,1)])
def test_exit_requires_clean_execution(count,error,status):
    out=evaluated(*base_case())
    assert output_exit_code(out,request_count=count,error=error,native_status=status)==1
