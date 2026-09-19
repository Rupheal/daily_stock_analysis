import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from dsa_production_orchestrator_v1 import classify_o,classify_u,orchestrate

NOW='2026-09-18T16:31:00+08:00'
TARGET='2026-09-18'
NEXT='2026-09-21'

def o_wait():
    return {'status':'ACCEPTED_O_FORMAL_TOP3','target_session':TARGET,'missing_count':0,
      'qualified_buy_in_Top3':0,'Top3':[
        {'code':'00148','rank':1,'sentiment_score':59,'action':'hold','action_family':'hold'},
        {'code':'00177','rank':2,'sentiment_score':59,'action':'hold','action_family':'hold'},
        {'code':'00552','rank':3,'sentiment_score':59,'action':'hold','action_family':'hold'}]}

def u_wait(session=TARGET):
    return {'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':session,
      'denominator':45,'formal_valid_rows':44,'qualified_BUY':0,'Top3':[],'rows':[]}

def write(tmp_path,name,obj):
    p=tmp_path/name;p.write_text(json.dumps(obj));return p

def test_current_wait_is_safe_without_journal(tmp_path):
    op=write(tmp_path,'o.json',o_wait());up=write(tmp_path,'u.json',u_wait())
    r=orchestrate(o_wait(),u_wait(),TARGET,NOW,NEXT,op,up,None,False)
    assert r['state']=='WAIT_NO_BUY'
    assert r['qualified_buy_total']==0
    assert [x['kind'] for x in r['commands']]==['SIGNAL','SIGNAL']
    assert all(x['signal']['passed'] is False for x in r['commands'])
    assert r['real_orders']==0

def test_stale_u_degrades_and_never_trades(tmp_path):
    op=write(tmp_path,'o.json',o_wait());u=u_wait('2026-09-17');up=write(tmp_path,'u.json',u)
    r=orchestrate(o_wait(),u,TARGET,NOW,NEXT,op,up,None,False)
    assert r['state']=='DEGRADED_STALE'
    assert r['tracks']['U']['state']=='STALE'
    assert not any(x['kind']=='ENTRY' for x in r['commands'])

def test_o_buy_claim_without_buyability_is_blocked():
    o=o_wait();o['qualified_buy_in_Top3']=1
    o['Top3'][0].update(action='buy',action_family='buy',industry='Materials')
    x=classify_o(o,TARGET)
    assert x['state']=='BLOCKED'
    assert 'O_BUYABILITY_NOT_VERIFIED' in x['blockers']

def test_u_buy_requires_zone_and_macro():
    u=u_wait();u.update(state='PASS_FORMAL_U_DECISION_BUY',qualified_BUY=1)
    u['Top3']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY'}]
    u['rows']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY','validation':'PASS',
                'buyable_verified':True,'industry':'Internet','zone_status':'WITHHELD_UNKNOWN',
                'zone_lower_hkd':None,'zone_upper_hkd':None,'macro_position_ceiling_pct':30}]
    x=classify_u(u,TARGET)
    assert x['state']=='BLOCKED'
    assert 'U_BUY_ZONE_NOT_APPROVED' in x['blockers']

def test_qualified_buy_blocks_entry_when_evidence_missing(tmp_path):
    u=u_wait();u.update(state='PASS_FORMAL_U_DECISION_BUY',qualified_BUY=1)
    u['Top3']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY'}]
    u['rows']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY','validation':'PASS',
                'buyable_verified':True,'industry':'Internet','zone_status':'APPROVED',
                'zone_lower_hkd':600,'zone_upper_hkd':630,'macro_position_ceiling_pct':30}]
    op=write(tmp_path,'o.json',o_wait());up=write(tmp_path,'u.json',u)
    r=orchestrate(o_wait(),u,TARGET,NOW,NEXT,op,up,None,False)
    assert r['state']=='BUY_ENTRY_BLOCKED'
    assert r['entry_blockers']['U']==['ENTRY_EVIDENCE_MISSING']
    assert not any(x['kind']=='ENTRY' for x in r['commands'])

def test_entry_command_only_with_verified_evidence_and_journal(tmp_path):
    u=u_wait();u.update(state='PASS_FORMAL_U_DECISION_BUY',qualified_BUY=1)
    u['Top3']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY'}]
    u['rows']=[{'code':'00700','rank':1,'score':80,'formal_action':'BUY','validation':'PASS',
                'buyable_verified':True,'industry':'Internet','zone_status':'APPROVED',
                'zone_lower_hkd':600,'zone_upper_hkd':630,'macro_position_ceiling_pct':30}]
    op=write(tmp_path,'o.json',o_wait());up=write(tmp_path,'u.json',u)
    ev={'U':{'code':'00700','at':'2026-09-21T09:30:00+08:00','price':'610','cny_per_hkd':'0.92',
      'lot_size':100,'fee_cny':'100','source':'verified-quote','sha256':'a'*64,
      'fx_source':'verified-fx','fx_sha256':'b'*64,'fx_at':'2026-09-21T09:29:00+08:00',
      'session':NEXT,'tradable':True,'first_eligible_price_verified':True,'lot_verified':True,
      'mode':'daily_open','next_session_verified':True}}
    r=orchestrate(o_wait(),u,TARGET,NOW,NEXT,op,up,ev,True)
    assert r['state']=='READY_FOR_SIMULATION_WRITE'
    entries=[x for x in r['commands'] if x['kind']=='ENTRY']
    assert len(entries)==1 and entries[0]['account']=='U'
    assert r['real_orders']==0
