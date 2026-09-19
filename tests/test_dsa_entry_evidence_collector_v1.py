from scripts.dsa_entry_evidence_collector_v1 import build
def good():
    q={'verified':True,'source':'quote','at':'2026-09-21T09:30:01+08:00','price':'10.5',
       'tradable':True,'adjustment':'raw','first_eligible_price_verified':True,'mode':'tick'}
    l={'verified':True,'source':'static','lot_size':100}
    fx={'verified':True,'source':'fx','at':'2026-09-21T09:29:59+08:00','cny_per_hkd':'0.91'}
    f={'verified':True,'source':'fee-policy-v1','fee_cny':'15'}
    i={'verified':True,'industry':'technology','source':'universe'}
    return q,l,fx,f,i
def test_all_verified_passes():
    q,l,fx,f,i=good();r=build('00700',q,l,fx,f,i)
    assert r['status']=='PASS_ENTRY_V1_EVIDENCE'
    assert r['evidence']['quote']['lot_size']==100
    assert r['real_orders']==0
def test_missing_fee_fails_closed():
    q,l,fx,f,i=good();r=build('00700',q,l,fx,None,i)
    assert r['status']=='BLOCKED_ENTRY_V1_EVIDENCE'
    assert 'FEE_POLICY_UNVERIFIED' in r['blockers']
def test_unverified_fx_fails_closed():
    q,l,fx,f,i=good();fx['verified']=False
    assert 'FX_UNVERIFIED' in build('00700',q,l,fx,f,i)['blockers']
def test_daily_open_needs_session_verification():
    q,l,fx,f,i=good();q['mode']='daily_open'
    r=build('00700',q,l,fx,f,i)
    assert r['status']=='BLOCKED_ENTRY_V1_EVIDENCE'
    assert 'NEXT_SESSION_UNVERIFIED' in r['blockers']
