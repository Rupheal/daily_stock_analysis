from copy import deepcopy
from pathlib import Path
import sys,json
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from build_u_member_reports import indicator_facts,policy_plan,build
from run_u_bounded_member_review import validate_response
ROOT=Path(__file__).parents[1]


def test_indicators_do_not_invent_macd_or_turnover_for_short_history():
    r=[dict(date=f'2026-08-{i:02}',open=i,high=i+1,low=i-1,close=i,volume=100) for i in range(1,22)]
    f=indicator_facts(r)
    assert f['ma5']==19 and f['rsi14']==100 and f['macd'] is None
    assert f['turnover_hkd'] is None and f['trend']=='BULLISH_MA_ORDER'


def test_real_u_packet_separates_reports_and_execution_requirements():
    d=json.loads((ROOT/'docs/runtime/RUN041_U45_MEMBER_REPORTS.json').read_text())
    assert d['coverage']['bounded_factual_reports_verified']==44
    assert d['coverage']['qualified_BUY']==0
    for m in d['members']:
        if m['plan']:
            assert m['plan']['executable_buy_zone'] is None
            assert 'timestamped_firm_ask_after_signal_and_order' in m['plan']['requires_at_execution']
            assert 'timestamped_firm_ask_after_signal_and_order' not in m['plan']['requires_before_signal']
            assert m['plan']['add_condition']=='PROHIBITED_FOR_FROZEN_SHADOW_ACCOUNT'
    assert next(m for m in d['members'] if m['code']=='09618')['action']=='NO_TRADE'


def sample():
    d=json.loads((ROOT/'docs/runtime/RUN041_U45_MEMBER_REPORTS.json').read_text());m=d['members'][0]
    row={'code':m['code'],'decision':'OBSERVE','trend':m['facts']['trend'],'news_state':m['news']['state'],
         'capital_state':m['capital']['status'],'evidence_ids':['price:'+m['code'],'technical:'+m['code']],
         'thesis':'量价与均线条件仍需要继续观察。','counterpoint':'新闻证据有限，尚不能排除未覆盖风险。'}
    return m,row


def test_observation_is_a_valid_review_not_a_buy():
    m,r=sample();accepted,failures=validate_response(json.dumps({'members':[r]}),[m])
    assert len(accepted)==1 and not failures and accepted[0]['decision']=='OBSERVE'


@pytest.mark.parametrize('key,value',[('decision','BUY'),('trend','INVENTED'),('news_state','NO_ADVERSE_NEWS'),('evidence_ids',['external:invented']),('thesis','明日股价将上涨百分之10')])
def test_fact_or_action_fabrication_is_isolated(key,value):
    m,r=sample();r[key]=value;a,f=validate_response(json.dumps({'members':[r]}),[m]);assert not a and len(f)==1


def test_duplicate_member_cannot_inflate_coverage():
    m,r=sample()
    with pytest.raises(ValueError,match='MEMBER_SET'):validate_response(json.dumps({'members':[r,r]}),[m])


@pytest.mark.parametrize('claim,expected',[('目前现价位于支撑上方，等待进一步确认。','U_LIVE_PRICE_WORD_WITHOUT_PRICE_TIME'),('动能柱转正，价格方向仍需进一步确认。','U_MACD_TRANSITION_WITHOUT_PREVIOUS_VALUE'),('价格进入超卖区域，存在潜在修复可能。','U_RSI_OVERSOLD_CONFLICT')])
def test_real_run044_classes_rejected_without_repeat_call(claim,expected):
    m,r=sample();m=deepcopy(m);m['facts']['rsi14']=35;m['facts']['macd']={'histogram_2x':1}
    r['thesis']=claim;a,f=validate_response(json.dumps({'members':[r]}),[m]);assert not a and f[0]['reason']==expected
