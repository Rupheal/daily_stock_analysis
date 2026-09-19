from scripts.u_production_daily_member_v1 import facts
def test_facts_from_rolling_bars():
    rows=[]
    for i in range(30):
        rows.append({'date':f'2026-08-{i+1:02d}','open':100+i,'high':101+i,'low':99+i,'close':100+i,'volume':1000+i})
    f=facts(rows)
    assert f['ma5'] is not None and f['ma20'] is not None
    assert f['return_20d_pct'] is not None
    assert f['observed_support20']==109
    assert f['observed_resistance20']==130
    assert f['turnover_hkd'] is None
