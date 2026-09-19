from scripts.u_production_close_refresh_v1 import build
def fixture():
    u={'members':[{'code':f'{i:05d}','official_name':str(i)} for i in range(1,46)]}
    h={'target_session':'2026-09-18','histories':{}}
    for i in range(1,46):
        h['histories']['hk'+f'{i:05d}']=[{'date':'2026-09-18','open':1,'high':2,'low':.5,'close':1.5,'volume':100}]
    return u,h
def test_45_current_pass():
    u,h=fixture();r=build(u,h,'2026-09-18')
    assert r['current_valid_count']==45 and r['status']=='PASS_CURRENT_SESSION_FACT_REFRESH'
def test_one_missing_is_partial():
    u,h=fixture();h['histories'].pop('hk00045')
    r=build(u,h,'2026-09-18')
    assert r['current_valid_count']==44 and r['facts'][-1]['current_valid_bar'] is False
