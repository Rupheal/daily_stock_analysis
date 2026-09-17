from copy import deepcopy
from test_o_single_output_fact_check import case,add_v2_execution_contract,codes
from o_single_output_fact_check import check_saved_output


def test_prior_bar_must_not_be_described_as_today_low_even_with_numeric_pass():
    p,i,r=case();add_v2_execution_contract(p,False)
    r['dashboard']={'phase_decision':{'phase_context':{'session_date':'2026-01-06'}}}
    r['plan']='目标交易日支撑为十元，今日盘中低点附近观察'
    assert 'SEM001_PREVIOUS_SESSION_RELABELLED_TODAY' in codes(check_saved_output(p,i,r))


def test_date_qualified_prior_low_is_valid():
    p,i,r=case();add_v2_execution_contract(p,False)
    r['dashboard']={'phase_decision':{'phase_context':{'session_date':'2026-01-06'}}}
    r['plan']='上一交易日低点为支撑参考，等待下一交易时段确认'
    assert 'SEM001_PREVIOUS_SESSION_RELABELLED_TODAY' not in codes(check_saved_output(p,i,r))


def test_one_repurchase_does_not_prove_no_adverse_news():
    p,i,r=case();p['risk_review_complete']=False;i['news_context']='发行人回购公告';r['checklist']='近三日无减持或处罚，故无重大利空'
    before=deepcopy((p,i,r));out=check_saved_output(p,i,r)
    assert 'SEM002_ADVERSE_NEWS_ABSENCE_CLAIM_WITH_INCOMPLETE_REVIEW' in codes(out)
    assert (p,i,r)==before


def test_missing_review_does_not_block_explicit_uncertainty():
    p,i,r=case();p['risk_review_complete']=False;i['news_context']='发行人回购公告';r['checklist']='只核验回购，不能排除其他负面新闻'
    assert 'SEM-002' not in check_saved_output(p,i,r)['triggered_semantic_guards']
