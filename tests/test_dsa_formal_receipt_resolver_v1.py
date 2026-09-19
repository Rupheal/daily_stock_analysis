import json
from pathlib import Path
from scripts.dsa_formal_receipt_resolver_v1 import resolve

def w(p,obj): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj))
def test_production_latest_wins_exact_target(tmp_path):
    w(tmp_path/'docs/runtime/O_PRODUCTION_FORMAL_LATEST.json',{'status':'ACCEPTED_O_FORMAL_TOP3','target_session':'2026-09-18','missing_count':0})
    w(tmp_path/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',{'status':'ACCEPTED_O_FORMAL_TOP3','target_session':'2026-09-17','missing_count':0})
    w(tmp_path/'docs/runtime/U_PRODUCTION_FORMAL_LATEST.json',{'state':'PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED','target_session':'2026-09-18','denominator':45})
    r=resolve(tmp_path,'2026-09-18')
    assert r['state']=='READY'
    assert r['O']['path'].endswith('O_PRODUCTION_FORMAL_LATEST.json')
    assert r['U']['path'].endswith('U_PRODUCTION_FORMAL_LATEST.json')
def test_historical_fallback_allowed_if_exact(tmp_path):
    w(tmp_path/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',{'status':'ACCEPTED_O_FORMAL_TOP3','target_session':'2026-09-18','missing_count':0})
    w(tmp_path/'docs/runtime/RUN056_U_FORMAL_RESULT.json',{'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':'2026-09-18','denominator':45})
    assert resolve(tmp_path,'2026-09-18')['state']=='READY'
def test_stale_never_selected(tmp_path):
    w(tmp_path/'docs/runtime/RUN076_O657_FORMAL_ACCEPTANCE.json',{'status':'ACCEPTED_O_FORMAL_TOP3','target_session':'2026-09-18','missing_count':0})
    w(tmp_path/'docs/runtime/RUN056_U_FORMAL_RESULT.json',{'state':'PASS_FORMAL_U_DECISION_WAIT_NO_BUY','target_session':'2026-09-17','denominator':45})
    r=resolve(tmp_path,'2026-09-18')
    assert r['state']=='MISSING_FORMAL_RECEIPT' and r['U']['path'] is None
