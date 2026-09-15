from copy import deepcopy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from o_single_output_fact_check import check_saved_output

def case():
    return ({'target':'2026-01-05','news_count':0},{'context':{'date':'2026-01-05','today':{'date':'2026-01-05','open':'10.0'},'yesterday':{'close':'10.2'}},'news_context':None},{'pattern_analysis':'低开','action':'watch','news_result_count_known':False,'news_result_count':None})
def codes(out):return [f['code'] for f in out['findings']]
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
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' in codes(check_saved_output(p,i,r))
def test_unknown_count_is_valid_unknown():
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' not in codes(check_saved_output(*case()))
def test_count_boolean_not_integer():
    p,i,r=case();r.update(news_result_count_known=True,news_result_count=True)
    assert 'NEWS_COUNT_KNOWN_WITHOUT_NONNEGATIVE_INTEGER' in codes(check_saved_output(p,i,r))
def test_actual_zero_count_known_is_consistent():
    p,i,r=case();r.update(news_result_count_known=True,news_result_count=0)
    assert 'NEWS_COUNT_METADATA_CONSISTENT' in check_saved_output(p,i,r)['checks_passed']
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
