import pytest
from src.services.dsa_market_observation import tencent_hk_observation,link_price

def raw(ts='2026/09/14 15:10:22'):
    f=['']*35
    for i,v in {2:'01810',3:'10.000',4:'9.000',30:ts,31:'1.000',32:'11.11'}.items():f[i]=v
    return ('v_r_hk01810="'+'~'.join(f)+'";').encode('gb18030')
def obs():return tencent_hk_observation(raw(),code='HK01810',retrieved_at='2026-09-14T15:11:00+08:00',source_locator='https://qt.gtimg.cn/q=r_hk01810')
def snap(t):return {'snapshot_id':'fixture','generated_at':t,'decision_cutoff':t}
def test_source_time_is_distinct_from_retrieval():
    x=obs();assert x['price_time']=='2026-09-14T15:10:22+08:00' and x['price_time']!=x['retrieved_at']
def test_stale_price_cannot_use_new_retrieval_time():
    with pytest.raises(ValueError,match='strictly after'):link_price(snap('2026-09-14T15:10:30+08:00'),obs(),'HK01810')
def test_matching_time_not_eligible():
    with pytest.raises(ValueError):link_price(snap(obs()['price_time']),obs(),'HK01810')
def test_valid_observation_is_not_trade():
    x=link_price(snap('2026-09-14T15:00:00+08:00'),obs(),'HK01810');assert not x['entry_authorized']
def test_missing_time_and_wrong_security_rejected():
    with pytest.raises(ValueError):tencent_hk_observation(raw(''),code='01810',retrieved_at='2026-09-14T15:11:00+08:00',source_locator='https://qt.gtimg.cn/q=r_hk01810')
    with pytest.raises(ValueError):link_price(snap('2026-09-14T15:00:00+08:00'),obs(),'HK00700')
