import copy
import pytest
from src.services.dsa_simulation_ledger import new_journal, append, replay, summary, save_atomic
from src.services.dsa_prediction_ledger import canonical_hash

# Synthetic fixtures only; no public prices or actual account data.
CFG={'accounts':{'U':'300000','O':'300000'},'u_denominator':45,'o_upstream_commit':'fixture-native',
     'rules':{'max_positions':3,'ticket_cny':'60000','ticket_cap':'.2','total_cap':'.6','industry_cap':'.4',
              'stop':'.02','tp1':'.05','tp2':'.10','moderate_score_drop':'.10','severe_score_drop':'.20'}}
EV={'verified':True,'source':'synthetic-fixture','sha256':'a'*64}
T0='2026-01-02T01:00:00+00:00';T1='2026-01-05T01:30:00+00:00';T2='2026-01-05T08:00:00+00:00'
def signal(passed=True,account='U'):
    return {'id':'signal-'+account,'account':account,'at':T0,'kind':'SIGNAL','signal':{
        **EV,'id':'morning','cutoff':T0,'available_at':T0,'scope':'forward_simulation','passed':passed,
        'covered':45,'denominator':45,'data_news_plan_verified':True,'next_session':'2026-01-05',
        'engine':'original_native_dsa','upstream_commit':'fixture-native',
        'top3':[{'code':'fixture','rank':1,'score':80,'industry':'fixture-industry','action':'BUY','buyable_verified':True}]}}
def quote():return {**EV,'at':T1,'price':'10','cny_per_hkd':'1','fx_evidence':{**EV,'at':T0},'tradable':True,
                   'adjustment':'raw','first_eligible_price_verified':True,'mode':'daily_open','next_session_verified':True,
                   'session':'2026-01-05','lot_size':100,'lot_verified':True}
def entry():return {'id':'entry','account':'U','at':T1,'kind':'ENTRY','signal_id':'morning','code':'fixture','quote':quote(),'fee_cny':'0'}
def bought():return append(append(new_journal(CFG),signal()),entry())
def bar(o='10',h='10.7',l='10.1',c='10.5'):
    return {'id':'bar','account':'U','at':T2,'kind':'BAR','code':'fixture','fee_cny_by_exit':{'STOP':'0','TP1':'0','TP2':'0'},
            'bar':{**EV,'id':'day1','open_at':T1,'close_at':T2,'open':o,'high':h,'low':l,'close':c,
                   'adjustment':'raw','corporate_actions_verified':True,'cny_per_hkd':'1','fx_evidence':{**EV,'at':T0}}}

def test_wait_and_duplicate_replay():
    j=append(new_journal(CFG),signal(False));j2=append(j,signal(False))
    assert j==j2 and summary(j)['accounts']['U']['buy_count']==0
    s=signal(False);s['signal']['reason']='changed'
    with pytest.raises(ValueError):append(j,s)

def test_no_lookahead():
    j=append(new_journal(CFG),signal());e=entry();e['at']=T0
    with pytest.raises(ValueError,match='availability'):append(j,e)

def test_adapter_and_partial_coverage_rejected():
    for field,val in [('engine','custom_adapter'),('covered',44)]:
        s=signal(account='O');s['signal'][field]=val
        with pytest.raises(ValueError):append(new_journal(CFG),s)

def test_duplicate_entry_has_no_second_fill():
    j=bought();assert append(j,entry())==j
    e=entry();e['id']='second';j=append(j,e)
    assert summary(j)['accounts']['U']['buy_count']==1
    assert replay(j)['U']['cash']=='240000'

def test_initial_stop_gap_and_daily_collision():
    for o,h,l,c in [('9','11','8','10'),('10','11','9','10')]:
        j=append(bought(),bar(o,h,l,c));s=summary(j)['accounts']['U']
        assert not s['positions'] and s['sell_count']==1
        assert s['events'][-2]['price']==('9' if o=='9' else '9.80')

def test_partial_tp_and_runner():
    j=append(bought(),bar('10.2','10.6','10.1','10.5'))
    p=replay(j)['U']['positions']['fixture'];assert p['qty']==4000 and p['stage']==1
    b=bar('10.6','11.2','10.5','11');b['id']='bar2';b['bar']['id']='day2'
    b['at']=b['bar']['close_at']='2026-01-06T08:00:00+00:00';b['bar']['open_at']='2026-01-06T01:30:00+00:00'
    j=append(j,b);p=replay(j)['U']['positions']['fixture'];assert p['qty']==2000 and p['stage']==2

def test_intraday_unknown_order_conservative():
    b=bar('10','11.2','9.99','11');j=append(bought(),b)
    s=summary(j)['accounts']['U'];assert not s['positions']
    assert [e.get('reason') for e in s['events'] if e['kind']=='SELL']==['TP1','AMBIGUOUS_BREAKEVEN']
    assert not s['net_performance_verified']

def test_tamper_and_local_cas(tmp_path):
    j=bought();p=tmp_path/'j.json';save_atomic(p,j)
    with pytest.raises(ValueError):save_atomic(p,j)
    save_atomic(p,j,canonical_hash(j))
    j['commands'][0]['command']['signal']['passed']=False
    with pytest.raises(ValueError,match='hash'):replay(j)

def test_fx_lot_fees_and_next_session_required():
    for mutate in [lambda e:e['quote'].update(cny_per_hkd='0'),lambda e:e['quote'].update(lot_verified=False),
                   lambda e:e['quote'].update(next_session_verified=False)]:
        e=entry();mutate(e)
        with pytest.raises(ValueError):append(append(new_journal(CFG),signal()),e)
    e=entry();e['fee_cny']=None;j=append(append(new_journal(CFG),signal()),e)
    assert summary(j)['accounts']['U']['buy_count']==0

def test_suspension_and_corporate_action_do_not_create_fill():
    for field in ['suspended','corporate_action']:
        b=bar();b['bar'][field]=True;j=append(bought(),b)
        assert summary(j)['accounts']['U']['sell_count']==0

def test_rank_decay_runner_and_missing_rank():
    j=append(bought(),bar('10.2','11.2','10.1','11'))
    assert replay(j)['U']['positions']['fixture']['stage']==2
    for i in range(2):
        r={**EV,'id':f'rank{i}','account':'U','at':f'2026-01-0{6+i}T08:30:00+00:00',
           'kind':'RANK','snapshot_id':f's{i}','complete_comparable_snapshot':True,
           'ranks':{'fixture':{'rank':11,'score':79}}}
        j=append(j,r)
    assert replay(j)['U']['positions']['fixture']['exit_pending']
    b=bar('10.8','11','10.5','10.8');b['id']='nextbar';b['bar']['id']='nextday'
    b['at']=b['bar']['close_at']='2026-01-08T08:00:00+00:00';b['bar']['open_at']='2026-01-08T01:30:00+00:00'
    j=append(j,b);assert not replay(j)['U']['positions']
    assert summary(j)['accounts']['U']['events'][-2]['reason']=='RANK_EXIT'

def test_incomplete_ranks_do_not_force_sale():
    j=bought();r={**EV,'id':'r','account':'U','at':T2,'kind':'RANK','snapshot_id':'s',
                'complete_comparable_snapshot':False,'ranks':{}}
    j=append(j,r);assert not replay(j)['U']['positions']['fixture']['exit_pending']

def test_overlapping_daily_bar_rejected():
    j=append(bought(),bar('10.2','10.6','10.1','10.5'));b=bar('10.2','10.6','10.1','10.5')
    b['id']='different-command';b['bar']['id']='same-session-other-provider'
    with pytest.raises(ValueError,match='overlapping'):append(j,b)

def test_independent_account_balance():
    j=bought();assert replay(j)['O']['cash']=='300000' and not replay(j)['O']['positions']
