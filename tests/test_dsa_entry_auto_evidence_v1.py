import json
from scripts.dsa_entry_auto_evidence_v1 import simulated_fee,build

POLICY={
 'policy_id':'DSA_SIMULATION_FEE_POLICY_v1','fee_rate_on_notional':'0.0020',
 'minimum_fee_cny':'20','sizing_reference_ticket_cny':'60000'
}
def parts():
    q={'verified':True,'source':'q','sha256':'a'*64,'at':'2026-09-21T09:30:00+08:00',
       'price':'10','tradable':True,'adjustment':'raw','first_eligible_price_verified':True,
       'mode':'daily_open','session':'2026-09-21','next_session_verified':True}
    lot={'verified':True,'source':'hkex','sha256':'b'*64,'lot_size':100}
    fx={'verified':True,'source':'fx','sha256':'c'*64,'at':'2026-09-21T09:29:00+08:00','cny_per_hkd':'0.92'}
    return q,lot,fx
def test_sim_fee_is_conservative_fixed_policy():
    assert simulated_fee(POLICY)=='120.0'
def test_auto_packet_passes_with_complete_sources():
    q,l,fx=parts();r=build('00700','2026-09-21',q,l,fx,POLICY,None)
    assert r['status']=='PASS_ENTRY_V1_EVIDENCE'
    assert r['evidence']['quote']['session']=='2026-09-21'
    assert r['evidence']['industry']=='UNCLASSIFIED'
    assert r['evidence']['fee_cny']=='120.0'
    assert r['real_orders']==0
def test_missing_quote_fails_closed():
    q,l,fx=parts();r=build('00700','2026-09-21',None,l,fx,POLICY,'Internet')
    assert r['status']=='BLOCKED_ENTRY_V1_EVIDENCE'
    assert 'QUOTE_UNVERIFIED' in r['blockers']
