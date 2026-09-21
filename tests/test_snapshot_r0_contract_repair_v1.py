import json,sys
from pathlib import Path
import pandas as pd
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import u_daily_data_integrity_v1 as q
import dsa_snapshot_r0_contract_v1 as s
T='2026-09-21'
def universe():return {'member_count':45,'members':[{'code':f'{i:05d}'} for i in range(1,46)]}
def bar(d=T):return {'date':d,'open':10.,'high':12.,'low':9.,'close':11.,'volume':100.}
def receipts(n):
    rows=[];facts=[]
    for i,m in enumerate(universe()['members']):
        c=m['code'];good=i<n
        if good:rows.append({'code':c,'data_session':T,'status':'PRODUCTION_TECHNICAL_FACT_REPORT','history_bars':21,'facts':{'close':11.}})
        facts.append({'code':c,'target_session':T,'latest_date':T,'current_valid_bar':good,**({k:v for k,v in bar().items() if k!='date'} if good else {})})
    return {'target_session':T,'current_member_count':n,'members':rows,'model_http_requests':0},{'target_session':T,'current_valid_count':n,'facts':facts,'model_http_requests':0}
@pytest.mark.parametrize('code,expected',[('00700','0700.HK'),('00005','0005.HK'),('03690','3690.HK'),('09988','9988.HK'),('10000','10000.HK')])
def test_yahoo_mapping(code,expected):assert q.yahoo_symbol(code)==expected and len(q.canonical_code(code))==5
@pytest.mark.parametrize('n',[0,1,44])
def test_partial_is_not_complete(n):
    r=q.assess_refresh(universe(),*receipts(n),T)
    assert r['r0_refresh_complete'] is False and r['state']=='WAIT_U_PRICE_DATA'
def test_full_45_is_price_only():
    r=q.assess_refresh(universe(),*receipts(45),T)
    assert r['r0_refresh_complete'] and not r['formal_generation_complete']
def test_fake_count_fails():
    m,c=receipts(0);c['current_valid_count']=45
    with pytest.raises(ValueError):q.assess_refresh(universe(),m,c,T)
def test_nonfinite_bar_fails():
    r=bar();r['close']=float('nan')
    with pytest.raises(ValueError):q.normalize_history([r],T)
def test_future_bar_removed():assert q.normalize_history([bar(T),bar('2026-09-22')],T)==[bar()]
def test_duplicate_bar_fails():
    with pytest.raises(ValueError):q.normalize_history([bar(),bar()],T)
def test_scalar_yahoo_columns(monkeypatch):
    import yfinance
    calls=[]
    def fake(symbol,**kw):
        calls.append((symbol,kw));return pd.DataFrame({'Open':[10.],'High':[12.],'Low':[9.],'Close':[11.],'Volume':[100.]},index=pd.to_datetime([T]))
    monkeypatch.setattr(yfinance,'download',fake)
    assert q.load_history('00700',T)==[bar()]
    assert calls[0][0]=='0700.HK' and calls[0][1]['multi_level_index'] is False

def seal():return {'status':'ACCEPTED_SAME_SESSION_R0_MEMBERSHIP_SEAL','target_session':T,'membership_code_count':2,'codes':['00001','03223'],'seal_id':'x','source_workflow_run':1,'source_artifact_id':2,'source_head_sha':'a'*40,'source_artifact_digest':'sha256:'+'b'*64,'source_universe_sha256':'c'*64}
def coverage():return {'expected_complete_session':T,'decision_session':T,'coverage_denominator':2,'requested_codes':['hk00001','hk03223'],'universe_sha256':'c'*64,'model_credentials_provided':False,'model_analysis_enabled':False}
def test_seal_cross_checked_with_original():assert s.validate_seal(seal(),T,coverage())==['00001','03223']
@pytest.mark.parametrize('field,value',[('universe_sha256','d'*64),('requested_codes',['hk00001','hk03224']),('expected_complete_session','2026-09-22')])
def test_seal_tamper_fails(field,value):
    c=coverage();c[field]=value
    with pytest.raises(ValueError):s.validate_seal(seal(),T,c)
def test_r0_never_promotes_identity(tmp_path):
    sp=tmp_path/'s.json';sp.write_text(json.dumps(seal()));up=tmp_path/'u.json';up.write_text(json.dumps(universe()))
    pp=tmp_path/'p.json';pp.write_text(json.dumps({'effective_session':'2026-09-18','members':[{'code':'00001','board_lot':100,'security_type':'stock'}]}))
    out=tmp_path/'out';r=s.materialize_r0(T,up,pp,sp,out)
    assert not r['formal_universe_available'] and r['identity_pending_count']==1 and not (out/'O_UNIVERSE.json').exists()
    assert all(not m['formal_identity_current_session_verified'] and m['board_lot'] is None for m in json.loads((out/'U_R0_UNIVERSE.json').read_text())['members'])
    pp.write_text(json.dumps({'effective_session':'2026-09-22','members':[]}))
    with pytest.raises(ValueError):s.materialize_r0(T,up,pp,sp,out)
def test_formal_identity_is_exact_session():
    import dsa_daily_market_snapshot_v1 as snap
    assert snap.identity_sessions_for_daily_snapshot(T)==[T]
