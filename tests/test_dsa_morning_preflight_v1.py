"""Synthetic price/identity evidence; never a real morning confirmation."""
import copy
import pytest
import exchange_calendars as xcals
from scripts.dsa_daily_formal_packet_v1 import build_o
from scripts.prepare_hk_o_operational_preflight_v3 import build_preflight


def fixture():
    dates=xcals.get_calendar('XHKG').sessions_in_range('2026-08-01','2026-09-25')
    bars=[{'date':d.date().isoformat(),'open':10,'high':11,'low':9,'close':10,
           'volume':1000,'ma5':10,'ma10':10,'ma20':10} for d in dates]
    u={'effective_session':'2026-09-28','full_union_verified':True,'member_count':1,
       'members':[{'code':'00001','official_name':'fixture','channels':['SSE']}], '_sha256':'a'*64}
    c={'expected_complete_session':'2026-09-25','coverage':[{'code':'00001','latest_date':'2026-09-25','status':'current_valid_bar'}]}
    p=build_o(u,c,'a'*64,'b'*64,'2026-09-28','2026-09-25')['policy'];p['_sha256']='c'*64
    cache={'target_session':'2026-09-25','histories':{'hk00001':bars},'_sha256':'b'*64}
    return u,cache,p,bars


def test_new_decision_uses_previous_prices_without_mutating_source():
    u,c,p,b=fixture();before=copy.deepcopy((u,c,p,b))
    r=build_preflight('00001','2026-09-25',u,c,p,b,{'source':'synthetic'})
    assert r['decision_session']=='2026-09-28'
    assert r['market_data_session']==r['today']['date']=='2026-09-25'
    assert r['facts']['date']=='2026-09-25'
    assert r['risk_review_complete'] is False
    assert (u,c,p,b)==before

@pytest.mark.parametrize('case',['stale_universe','wrong_cache','false_policy','bad_price'])
def test_morning_source_mismatch_rejected(case):
    u,c,p,b=fixture()
    if case=='stale_universe':u['effective_session']='2026-09-24'
    if case=='wrong_cache':c['target_session']='2026-09-24'
    if case=='false_policy':p['current_session']['market_data_session']='2026-09-24'
    if case=='bad_price':b=copy.deepcopy(b);b[-1]['close']=10.1
    with pytest.raises(ValueError):build_preflight('00001','2026-09-25',u,c,p,b,{'source':'synthetic'})
