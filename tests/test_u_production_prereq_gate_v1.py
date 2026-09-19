from scripts.u_production_prereq_gate_v1 import evaluate

TARGET='2026-09-18'
def close(t=TARGET): return {'target_session':t,'denominator':45,'current_valid_count':45}
def macro(t=TARGET): return {'target_session':t,'regime':{'position_ceiling_pct':30},'result':{'formal_macro_cap_available':True}}
def risk(t=TARGET): return {'target_session':t,'counts':{'denominator':45},'result':{'risk_evidence_bound':True}}
def zone(t=TARGET): return {'target_session':t,'denominator':45,'state':'PASS_CONTRACT_ONLY_FORMAL_MEMBER_ZONES_PENDING_RUN056'}

def test_all_current_allows_formal_provider():
    r=evaluate(TARGET,close(),macro(),risk(),zone())
    assert r['state']=='READY_FOR_U_FORMAL_PROVIDER'
    assert r['formal_provider_permitted'] is True
    assert r['fallback_formal_receipt'] is None

def test_stale_macro_fails_closed_without_provider():
    r=evaluate(TARGET,close(),macro('2026-09-17'),risk(),zone())
    assert r['formal_provider_permitted'] is False
    assert 'U_MACRO_CAP_NOT_CURRENT' in r['blockers']
    f=r['fallback_formal_receipt']
    assert f['state']=='PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED'
    assert f['qualified_BUY']==0 and f['provider_skipped'] is True

def test_missing_risk_zone_produces_wait():
    r=evaluate(TARGET,close(),macro(),None,None)
    assert set(r['blockers'])=={'U_RISK_EVIDENCE_NOT_CURRENT','U_ZONE_CONTRACT_NOT_CURRENT'}
    assert r['fallback_formal_receipt']['resource_accounting']['model_http_requests_confirmed']==0
