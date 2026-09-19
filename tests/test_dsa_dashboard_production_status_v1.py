from scripts.dsa_dashboard_production_status_v1 import build
def test_not_run():
    assert build(None,None)['status']=='NOT_RUN'
def test_runtime_status():
    r=build({'state':'SIMULATION_LEDGER_UPDATED','real_orders':0,'simulation_write_performed':True,
      'route':{'target_session':'2026-09-18','next_session':'2026-09-21'},
      'orchestrator':{'tracks':{'O':{'state':'WAIT'},'U':{'state':'BLOCKED'}},'entry':{'state':'NO_ENTRY'}}},
      {'state':'JOURNAL_INITIALIZED','command_count':2})
    assert r['O_state']=='WAIT' and r['U_state']=='BLOCKED' and r['journal_command_count']==2
