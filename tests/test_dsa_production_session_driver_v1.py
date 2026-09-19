from scripts.dsa_production_session_driver_v1 import drive

def o(session):
    return {'status':'ACCEPTED_O_FORMAL_TOP3','target_session':session,'missing_count':0}
def u(session):
    return {'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':session}

def test_monday_preopen_consumes_friday_close():
    r=drive('2026-09-21T09:00:00+08:00',o('2026-09-18'),u('2026-09-18'))
    assert r['window']=='PREOPEN'
    assert r['target_session']=='2026-09-18'
    assert r['next_session']=='2026-09-21'
    assert r['state']=='READY_FOR_ORCHESTRATOR'

def test_monday_preopen_stale_u_requests_only_u_refresh():
    r=drive('2026-09-21T09:00:00+08:00',o('2026-09-18'),u('2026-09-17'))
    assert r['state']=='NEEDS_FORMAL_REFRESH'
    assert r['tracks']['O']['fresh'] is True
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
    assert r['state']=='OFF_WINDOW_NO_ACTION'
    assert r['production_orchestrator_permitted'] is False
