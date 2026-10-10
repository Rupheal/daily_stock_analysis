"""Synthetic, offline regressions through orchestration and the real journal."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.dsa_production_orchestrator_v1 import (
    O_UPSTREAM, classify_o, orchestrate, filter_commands_against_journal,
)
from scripts.dsa_formal_receipt_resolver_v1 import resolve
from src.services.dsa_simulation_ledger import new_journal, append, replay

TARGET='2026-09-21'
NEXT='2026-09-22'
NOW='2026-09-21T17:30:00+08:00'
LATER='2026-09-21T17:31:00+08:00'


def inputs():
    timing={'cutoff':'2026-09-21T16:00:00+08:00',
            'available_at':'2026-09-21T17:29:00+08:00',
            'valid_until':'2026-09-25T17:29:00+08:00','next_session':NEXT}
    o={'status':'ACCEPTED_O_FORMAL_TOP3','target_session':TARGET,
       'official_O_denominator':662,'operational_O_denominator':659,
       'missing_count':0,'qualified_buy_in_Top3':0,'Top3':[],
       'signal_timing':copy.deepcopy(timing)}
    u={'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':TARGET,
       'denominator':45,'formal_valid_rows':44,'qualified_BUY':0,
       'Top3':[],'rows':[],'signal_timing':copy.deepcopy(timing)}
    return o,u


def paths(root,o,u):
    root.mkdir(parents=True,exist_ok=True)
    op=root/'o.json';up=root/'u.json'
    op.write_text(json.dumps(o));up.write_text(json.dumps(u))
    return op,up


def run(root,o,u,now=NOW):
    op,up=paths(root,o,u)
    return orchestrate(o,u,TARGET,now,NEXT,op,up,journal_configured=True)


def test_retry_after_clock_change_and_relocation_is_byte_stable(tmp_path):
    o,u=inputs()
    first=run(tmp_path/'consumer1',o,u)
    retry=run(tmp_path/'consumer2',o,u,LATER)
    assert first['generated_at']!=retry['generated_at']
    assert json.dumps(first['commands'],sort_keys=True)==json.dumps(retry['commands'],sort_keys=True)
    cfg={'accounts':{'O':'300000','U':'300000'},'u_denominator':45,
         'o_upstream_commit':O_UPSTREAM,'rules':{}}
    journal=new_journal(cfg)
    for command in first['commands']:
        journal=append(journal,command)
    pending,noops=filter_commands_against_journal(retry['commands'],journal)
    assert pending==[] and len(noops)==2
    for command in retry['commands']:
        assert append(journal,command)==journal
    assert all(not x['positions'] for x in replay(journal).values())


def test_coverage_uses_source_and_preserves_partial_u(tmp_path):
    o,u=inputs();result=run(tmp_path,o,u)
    signals={c['account']:c['signal'] for c in result['commands']}
    assert signals['O']['denominator']==signals['O']['covered']==659
    assert signals['U']['denominator']==45 and signals['U']['covered']==44


def test_current_wait_dynamic_denominator_resolves_and_reports_zero_coverage(tmp_path):
    o,u=inputs()
    o.update(status='PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING',current_session_formal_signals=0)
    root=tmp_path/'docs/runtime';root.mkdir(parents=True)
    (root/'O_PRODUCTION_FORMAL_LATEST.json').write_text(json.dumps(o))
    (root/'U_PRODUCTION_FORMAL_LATEST.json').write_text(json.dumps(u))
    assert resolve(tmp_path,TARGET)['state']=='READY'
    result=run(tmp_path/'output',o,u)
    assert result['state']=='WAIT_NO_BUY'
    assert result['commands'][0]['signal']['covered']==0
    assert result['commands'][0]['signal']['denominator']==659


@pytest.mark.parametrize('bad',[None,0,-1,663,True,'659'])
def test_invalid_o_denominator_blocks_without_default(tmp_path,bad):
    o,u=inputs();o['operational_O_denominator']=bad
    result=run(tmp_path,o,u)
    assert result['state']=='BLOCKED'
    assert not any(c['account']=='O' for c in result['commands'])


def test_missing_source_time_never_uses_execution_clock(tmp_path):
    o,u=inputs();del o['signal_timing']
    result=run(tmp_path,o,u)
    assert result['state']=='BLOCKED'
    assert result['entry_blockers']['O']==['SIGNAL_TIMING_MISSING']
    assert not any(c['account']=='O' for c in result['commands'])


@pytest.mark.parametrize('field,value,reason',[
    ('available_at','2026-09-21T17:29:00','SIGNAL_TIMING_INVALID'),
    ('cutoff','2026-09-21T17:30:00+08:00','SIGNAL_TIMING_ORDER_INVALID'),
    ('valid_until','2026-09-21T17:28:00+08:00','SIGNAL_TIMING_ORDER_INVALID'),
    ('available_at','2026-09-21T17:31:00+08:00','SIGNAL_NOT_YET_AVAILABLE'),
    ('next_session','2026-09-23','SIGNAL_NEXT_SESSION_MISMATCH'),
])
def test_invalid_or_future_timing_fails_closed(tmp_path,field,value,reason):
    o,u=inputs();o['signal_timing'][field]=value
    result=run(tmp_path,o,u)
    assert reason in result['entry_blockers']['O']
    assert not any(c['account']=='O' for c in result['commands'])


def test_receipt_and_classified_input_mismatch_is_blocked(tmp_path):
    o,u=inputs();op,up=paths(tmp_path,o,u)
    o['operational_O_denominator']=658
    result=orchestrate(o,u,TARGET,NOW,NEXT,op,up)
    assert result['entry_blockers']['O']==['SIGNAL_RECEIPT_CONTENT_MISMATCH']


def test_signal_tampering_still_rejected(tmp_path):
    o,u=inputs();result=run(tmp_path,o,u)
    old=result['commands'][0];changed=copy.deepcopy(old)
    changed['signal']['denominator']=657
    with pytest.raises(ValueError,match='COMMAND_ID_CONTENT_DRIFT'):
        filter_commands_against_journal([changed],{'commands':[{'command':old}]})


def test_new_receipt_bytes_get_new_identity(tmp_path):
    o,u=inputs();first=run(tmp_path/'first',o,u)
    o['signal_timing']['available_at']='2026-09-21T17:29:30+08:00'
    second=run(tmp_path/'second',o,u)
    assert first['commands'][0]['id']!=second['commands'][0]['id']


def test_expired_source_cannot_be_refreshed_by_retry(tmp_path):
    o,u=inputs()
    result=run(tmp_path,o,u,'2026-09-26T09:00:00+08:00')
    assert result['state']=='BLOCKED' and result['commands']==[]
    assert result['entry_blockers']=={'O':['SIGNAL_EXPIRED'],'U':['SIGNAL_EXPIRED']}


def test_qualified_u_entry_replays_once_with_source_availability(tmp_path):
    o,u=inputs()
    u.update(state='PASS_FORMAL_U_DECISION_BUY',qualified_BUY=1,
             Top3=[{'code':'fixture','rank':1,'score':80,'formal_action':'BUY'}],
             rows=[{'code':'fixture','rank':1,'score':80,'formal_action':'BUY',
                    'validation':'PASS','buyable_verified':True,'industry':'fixture-industry',
                    'zone_status':'APPROVED','zone_lower_hkd':9,'zone_upper_hkd':11,
                    'macro_position_ceiling_pct':60}])
    entry={'U':{'code':'fixture','at':'2026-09-22T09:30:00+08:00','price':'10','cny_per_hkd':'1',
                'lot_size':100,'fee_cny':'0','source':'synthetic-quote','sha256':'a'*64,
                'fx_source':'synthetic-fx','fx_sha256':'b'*64,'fx_at':'2026-09-22T09:29:00+08:00',
                'session':NEXT,'tradable':True,'first_eligible_price_verified':True,
                'lot_verified':True,'mode':'daily_open','next_session_verified':True}}
    op,up=paths(tmp_path,o,u)
    first=orchestrate(o,u,TARGET,'2026-09-22T09:35:00+08:00',NEXT,op,up,entry,True)
    retry=orchestrate(o,u,TARGET,'2026-09-22T09:36:00+08:00',NEXT,op,up,entry,True)
    assert first['state']=='READY_FOR_SIMULATION_WRITE'
    cfg={'accounts':{'O':'300000','U':'300000'},'u_denominator':45,'o_upstream_commit':O_UPSTREAM,
         'rules':{'max_positions':3,'ticket_cny':'60000','ticket_cap':'.2','total_cap':'.6','industry_cap':'.4',
                  'stop':'.02','tp1':'.05','tp2':'.10','moderate_score_drop':'.10','severe_score_drop':'.20'}}
    journal=new_journal(cfg)
    for command in first['commands']:
        journal=append(journal,command)
    assert filter_commands_against_journal(retry['commands'],journal)[0]==[]
    assert replay(journal)['U']['positions']['fixture']['qty']==6000
    assert replay(journal)['O']['positions']=={}
