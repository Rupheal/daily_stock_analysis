from scripts.dsa_production_session_driver_v1 import drive
import pytest

def o(session):
    return {'status':'ACCEPTED_O_FORMAL_TOP3','target_session':session,'missing_count':0}
def u(session):
    return {'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':session}

def test_monday_preopen_requires_new_morning_receipt():
    r=drive('2026-09-21T09:00:00+08:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']=='PREOPEN'
    assert r['target_session']=='2026-09-21'
    assert r['market_data_session']=='2026-09-18'
    assert r['next_session']=='2026-09-22'
    assert r['state']=='NEEDS_FORMAL_REFRESH'

def test_monday_preopen_stale_u_requests_only_u_refresh():
    r=drive('2026-09-21T09:00:00+08:00',o('2026-09-18'),u('2026-09-17'))
    assert r['state']=='NEEDS_FORMAL_REFRESH'
    assert r['tracks']['O']['fresh'] is False
    assert r['tracks']['U']['fresh'] is False
    assert r['tracks']['U']['required_action']=='REFRESH_U_FORMAL'
    assert r['production_orchestrator_permitted'] is False

def test_monday_postclose_advances_to_monday_session():
    r=drive('2026-09-21T16:30:00+08:00',o('2026-09-21'),u('2026-09-21'))
    assert r['window']=='POSTCLOSE'
    assert r['target_session']=='2026-09-21'
    assert r['next_session']=='2026-09-22'
    assert r['state']=='READY_FOR_ORCHESTRATOR'

def test_weekend_off_window_never_advances_session():
    r=drive('2026-09-19T12:00:00+08:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']=='OFF_WINDOW'
    assert r['target_session']=='2026-09-18'
    assert r['market_data_session']=='2026-09-18'
    assert r['state']=='OFF_WINDOW_NO_ACTION'
    assert r['production_orchestrator_permitted'] is False


def test_monday_entry_rejects_friday_formal_as_morning():
    r=drive('2026-09-21T09:35:00+08:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']=='ENTRY'
    assert r['target_session']=='2026-09-21'
    assert r['market_data_session']=='2026-09-18'
    assert r['next_session']=='2026-09-22'
    assert r['state']=='NEEDS_FORMAL_REFRESH'


@pytest.mark.parametrize('clock,expected',[
    ('09:29:59','OFF_WINDOW'),('09:30:00','ENTRY'),
    ('09:59:59','ENTRY'),('10:00:00','OFF_WINDOW'),
    ('10:00:01','OFF_WINDOW'),('10:15:00','OFF_WINDOW'),
])
def test_approved_entry_window_boundaries(clock,expected):
    r=drive('2026-09-21T'+clock+'+08:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']==expected
    assert r['production_orchestrator_permitted'] is False


@pytest.mark.parametrize('clock',['09:00:00','09:35:00','16:30:00'])
@pytest.mark.parametrize('day',['2026-09-19','2026-09-20','2026-10-01'])
def test_non_session_blocks_every_clock_window(day,clock):
    from scripts.dsa_production_session_driver_v1 import CAL
    target=CAL.date_to_session(day,direction='previous').date().isoformat()
    r=drive(day+'T'+clock+'+08:00',o(target),u(target))
    assert r['state']=='OFF_WINDOW_NO_ACTION'
    assert r['window']=='OFF_WINDOW'
    assert r['production_orchestrator_permitted'] is False


def test_entry_boundary_uses_hong_kong_not_input_timezone():
    r=drive('2026-09-21T02:00:00+00:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']=='OFF_WINDOW'


def test_current_morning_routes_to_existing_entry_gate(tmp_path):
    from test_dsa_entry_binding_v1 import inputs, t
    left,right,_,_=inputs(tmp_path)
    left['market_data_session']=right['market_data_session']='2026-09-23'
    r=drive(t('09:35:00'),left,right)
    assert r['state']=='READY_FOR_ORCHESTRATOR'
    assert not r['entry_policy_acceptance_verified']
    right['signal_timing']=dict(right['signal_timing'],available_at=t('09:25:01'))
    r=drive(t('09:35:00'),left,right)
    assert r['tracks']['O']['fresh'] and not r['tracks']['U']['fresh']
    assert r['morning_blockers']['U']==['CURRENT_PRE_FREEZE_TIMING_REQUIRED']

@pytest.mark.parametrize('field,value', [('market_data_session','2026-09-22'),('target_session','2026-09-23')])
def test_morning_dates_cannot_be_relabelled(tmp_path,field,value):
    from test_dsa_entry_binding_v1 import inputs, t
    left,right,_,_=inputs(tmp_path)
    left['market_data_session']=right['market_data_session']='2026-09-23'
    left[field]=value
    assert not drive(t('09:35:00'),left,right)['tracks']['O']['fresh']
