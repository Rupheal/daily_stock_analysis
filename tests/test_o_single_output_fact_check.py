from copy import deepcopy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from o_single_output_fact_check import check_saved_output

def case():
    return ({'target':'2026-01-05','news_count':0},{'context':{'date':'2026-01-05','today':{'date':'2026-01-05','open':'10.0'},'yesterday':{'close':'10.2'}},'news_context':None},{'pattern_analysis':'低开','action':'watch','news_result_count_known':False,'news_result_count':None,'current_price':None,'search_performed':False})
def add_v2_execution_contract(preflight, realtime):
    preflight['execution_contract']={'version':'O_GATE_A_EXECUTION_CONTRACT_v2','target_session':preflight['target'],
                                     'realtime_quote_available':realtime,'session_fact_anchor_required':True}
def codes(out):return [f['code'] for f in out['findings']]
def guards(out):return out['triggered_semantic_guards']
def test_high_open_contradicts_lower_actual_open():
    p,i,r=case();r['pattern_analysis']='高开，开盘高于前收'
    assert 'OPEN_GAP_DIRECTION_CONTRADICTION' in codes(check_saved_output(p,i,r))
def test_low_open_consistent():
    assert check_saved_output(*case())['semantic_verdict']=='NO_BLOCK_IN_CHECKED_SCOPE'
def test_equal_open_is_not_high_open():
    p,i,r=case();i['context']['yesterday']['close']='10';r['pattern_analysis']='高开'
    assert 'OPEN_GAP_DIRECTION_CONTRADICTION' in codes(check_saved_output(p,i,r))
def test_known_null_count_is_not_zero():
    p,i,r=case();r['news_result_count_known']=True
    assert check_saved_output(p,i,r)['news_state_sidecar']['state']=='NOT_SEARCHED'
def test_unknown_count_is_valid_unknown():
    assert 'NEWS_COUNT_KNOWN_WITHOUT_VALID_TRISTATE' not in codes(check_saved_output(*case()))
def test_count_boolean_not_integer():
    p,i,r=case();r.update(news_result_count_known=True,news_result_count=True)
    assert 'NEWS_COUNT_KNOWN_WITHOUT_VALID_TRISTATE' in codes(check_saved_output(p,i,r))
def test_actual_zero_count_known_is_consistent():
    p,i,r=case();r.update(news_result_count_known=True,news_result_count=0)
    assert 'NATIVE_NEWS_TRISTATE_CONSISTENT' in check_saved_output(p,i,r)['checks_passed']
def test_news_precheck_not_assumed_to_have_been_in_native_prompt():
    p,i,r=case();p['news_count']=4
    assert 'PREFLIGHT_NEWS_NOT_DELIVERED_TO_NATIVE_INPUT' in codes(check_saved_output(p,i,r))
def test_nonfinite_inputs_block():
    p,i,r=case();i['context']['today']['open']='NaN'
    assert 'OPEN_GAP_UNVERIFIABLE' in codes(check_saved_output(p,i,r))
def test_saved_originals_never_mutated_and_target_mismatch_blocked():
    p,i,r=case();i['context']['date']='2026-01-02';before=deepcopy((p,i,r))
    v=check_saved_output(p,i,r);assert (p,i,r)==before
    assert 'INPUT_TARGET_MISMATCH' in codes(v) and not v['runtime_activated']

def test_sem001_dashboard_current_price_without_realtime_quote():
    p,i,r=case();r['dashboard']={'data_perspective':{'price_position':{'current_price':10.1}}}
    assert 'SEM-001' in guards(check_saved_output(p,i,r))
def test_sem001_text_live_price_without_realtime_quote():
    p,i,r=case();r['analysis_summary']='现价10.10元贴近MA5'
    assert 'SEM001_LIVE_PRICE_LABEL_WITHOUT_REALTIME_QUOTE' in codes(check_saved_output(p,i,r))
def test_sem001_safe_completed_close_language():
    p,i,r=case();r['analysis_summary']='实时行情缺失，仅使用上一交易日收盘价10.10元'
    assert 'SEM-001' not in guards(check_saved_output(p,i,r))
def test_sem001_v2_false_contract_blocks_numeric_toplevel_current_price():
    p,i,r=case();add_v2_execution_contract(p,False);r['current_price']=10.1
    out=check_saved_output(p,i,r)
    assert 'SEM001_TOPLEVEL_CURRENT_PRICE_WITHOUT_REALTIME_QUOTE' in codes(out)
    assert 'SEM-001' in guards(out)
def test_sem001_v2_false_contract_blocks_numeric_dashboard_even_when_toplevel_numeric():
    p,i,r=case();add_v2_execution_contract(p,False);r['current_price']=10.1
    r['dashboard']={'data_perspective':{'price_position':{'current_price':10.1}}}
    out=check_saved_output(p,i,r)
    assert 'SEM001_TOPLEVEL_CURRENT_PRICE_WITHOUT_REALTIME_QUOTE' in codes(out)
    assert 'SEM001_LIVE_PRICE_FIELD_WITHOUT_REALTIME_QUOTE' in codes(out)
def test_sem001_v2_true_contract_is_authoritative_over_missing_output_field():
    p,i,r=case();add_v2_execution_contract(p,True)
    r['dashboard']={'data_perspective':{'price_position':{'current_price':10.1}}}
    r['analysis_summary']='现价10.10元'
    assert 'SEM-001' not in guards(check_saved_output(p,i,r))
def test_sem001_v2_invalid_realtime_availability_fails_closed():
    p,i,r=case();add_v2_execution_contract(p,False);p['execution_contract']['realtime_quote_available']='false'
    out=check_saved_output(p,i,r)
    assert 'SEM001_REALTIME_AVAILABILITY_CONTRACT_INVALID' in codes(out)
    assert 'SEM-001' in guards(out)
def test_sem001_v2_false_contract_safe_completed_close_language():
    p,i,r=case();add_v2_execution_contract(p,False)
    r['analysis_summary']='实时行情缺失，仅使用2026-01-05目标交易日收盘价10.10元'
    assert 'SEM-001' not in guards(check_saved_output(p,i,r))
def test_sem002_absence_of_bad_news_claim_when_news_missing():
    p,i,r=case();r['checklist']='未见近3日利空公告'
    assert 'SEM-002' in guards(check_saved_output(p,i,r))
def test_sem002_uncertainty_language_is_safe():
    p,i,r=case();r['checklist']='新闻数据缺失，无法排查近3日重大利空'
    assert 'SEM-002' not in guards(check_saved_output(p,i,r))
def test_sem003_index_fact_without_search_or_frozen_evidence():
    p,i,r=case();r['sector_position']='公司是恒生科技指数权重股之一'
    assert 'SEM-003' in guards(check_saved_output(p,i,r))
def test_sem003_index_fact_allowed_when_frozen_evidence_has_fact():
    p,i,r=case();i['context']['note']='小米是恒生科技指数权重股之一';r['sector_position']='公司是恒生科技指数权重股之一'
    assert 'SEM-003' not in guards(check_saved_output(p,i,r))
def test_sem003_not_checked_when_search_was_performed():
    p,i,r=case();r['search_performed']=True;r['sector_position']='公司是恒生科技指数权重股之一'
    assert 'SEM-003' not in guards(check_saved_output(p,i,r))
def test_guards_are_deterministic_and_do_not_mutate_inputs():
    p,i,r=case();r.update(checklist='未见近3日利空公告',sector_position='恒生科技指数权重股之一')
    before=deepcopy((p,i,r));a=check_saved_output(p,i,r);b=check_saved_output(p,i,r)
    assert a==b and (p,i,r)==before and a['new_model_requests']==0
