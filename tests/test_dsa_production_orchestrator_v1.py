import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from dsa_formal_signal_envelope_v1 import build
from dsa_qualified_buy_gate_v1 import gate
from dsa_build_simulation_commands_v1 import commands

def test_current_accepted_o_u_are_wait_and_generate_only_signal_commands(tmp_path):
    cal={'sessions':['2026-09-17','2026-09-18','2026-09-21']}
    env=build(ROOT/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',
              ROOT/'docs/runtime/RUN056_U_FORMAL_RESULT.json',cal)
    assert env['signals']['O']['passed'] is False
    assert env['signals']['U']['passed'] is False
    assert env['signals']['O']['reason']=='WAIT_NO_QUALIFIED_BUY'
    assert env['signals']['U']['reason']=='WAIT_NO_QUALIFIED_BUY'
    g=gate(env)
    assert g['tracks']['O']['state']==g['tracks']['U']['state']=='WAIT_NO_BUY'
    cmds=commands(env)
    assert [x['kind'] for x in cmds]==['SIGNAL','SIGNAL']
    assert all(x['signal']['scope']=='forward_simulation' for x in cmds)

def test_u_buy_requires_buyable_verified(tmp_path):
    cal={'sessions':['2026-09-17','2026-09-18']}
    u=json.loads((ROOT/'docs/runtime/RUN056_U_FORMAL_RESULT.json').read_text())
    u['state']='PASS_FORMAL_U_DECISION_BUY'
    row=u['rows'][0];row['formal_action']='BUY';row['buyable_verified']=True
    u['qualified_BUY']=1
    u['Top3']=[{'code':row['code'],'name':row['name'],'rank':1,'score':row['score'],'formal_action':'BUY'}]
    p=tmp_path/'u.json';p.write_text(json.dumps(u))
    env=build(ROOT/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',p,cal)
    assert env['signals']['U']['passed'] is True
    assert gate(env)['tracks']['U']['state']=='QUALIFIED_BUY'

def test_entry_commands_only_from_pass_receipt():
    env={'signals':{
      'O':{'id':'O:x','available_at':'2026-09-18T16:30:00+08:00'},
      'U':{'id':'U:x','available_at':'2026-09-18T16:30:00+08:00'}}}
    e={'entries':[{'status':'BLOCKED','command_id':'E1'},
                  {'status':'PASS_ENTRY_V1','command_id':'E2','account':'U','at':'2026-09-21T09:30:00+08:00',
                   'signal_id':'U:x','code':'00700','quote':{},'fee_cny':'1','excluded':{}}]}
    c=commands(env,e)
    assert sum(x['kind']=='ENTRY' for x in c)==1
    assert c[-1]['id']=='E2'
