import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("p",ROOT/"scripts/dsa_daily_formal_packet_v1.py")
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

TARGET="2026-09-22"

def universe(n=5):
    return {"full_union_verified":True,"effective_session":TARGET,"member_count":n,
            "members":[{"code":f"{i:05d}","official_name":f"N{i}"} for i in range(1,n+1)]}

def coverage(n=5,bad=None):
    bad=bad or {}
    return {"expected_complete_session":TARGET,"coverage":[
      {"code":"hk"+f"{i:05d}","status":bad.get(i,"current_valid_bar"),"latest_date":TARGET,"bars":50}
      for i in range(1,n+1)]}

def test_o_packet_is_session_dynamic_and_preserves_official_denominator():
    r=p.build_o(universe(),coverage(bad={2:"invalid_or_stale"}),"u"*64,"h"*64,TARGET)
    assert r["official_denominator"]==5
    assert r["operational_denominator"]==4
    assert r["policy"]["current_session"]["session"]==TARGET
    assert r["policy"]["current_session"]["excluded_unresolved"][0]["code"]=="00002"
    assert r["ledger"]["session"]==TARGET
    assert r["scope"]["target_session"]==TARGET
    assert "20260918" not in r["scope"]["run_id"]

def test_o_packet_rejects_stale_universe():
    u=universe();u["effective_session"]="2026-09-21"
    try:p.build_o(u,coverage(),"u"*64,"h"*64,TARGET)
    except ValueError as e:assert "CURRENT_OFFICIAL_UNIVERSE" in str(e)
    else:assert False

def u_inputs(current=True):
    t=TARGET if current else "2026-09-21"
    close={"target_session":TARGET,"denominator":45,"current_valid_count":45}
    macro={"target_session":t,"result":{"formal_macro_cap_available":True}}
    risk={"target_session":t,"rows":[{} for _ in range(45)]}
    zone={"target_session":t,"rows":[{} for _ in range(45)]}
    return close,macro,risk,zone

def test_u_packet_allows_provider_only_when_all_prerequisites_current():
    r=p.build_u(*u_inputs(True),TARGET)
    assert r["state"]=="READY_FOR_U_FORMAL_PROVIDER"
    assert r["provider_permitted"] is True

def test_u_packet_names_stale_prerequisites_instead_of_zero_buy():
    r=p.build_u(*u_inputs(False),TARGET)
    assert r["state"]=="WAIT_U_PREREQUISITES"
    assert set(r["blockers"])=={"U_MACRO_CAP_NOT_CURRENT","U_RISK_EVIDENCE_NOT_CURRENT","U_ZONE_CONTRACT_NOT_CURRENT"}
    assert r["provider_permitted"] is False


def test_new_morning_packet_keeps_price_date_and_current_universe():
    c=coverage();c['expected_complete_session']='2026-09-21'
    for row in c['coverage']: row['latest_date']='2026-09-21'
    r=p.build_o(universe(),c,'u'*64,'h'*64,TARGET,'2026-09-21')
    assert r['scope']['decision_session']==TARGET
    assert r['scope']['market_data_session']=='2026-09-21'
    assert r['policy']['current_session']['session']==TARGET
    assert r['scope']['no_orders'] is True

def test_morning_rejects_old_and_falsely_labelled_bars():
    import pytest
    with pytest.raises(ValueError,match='MARKET_SESSION'):
        p.build_o(universe(),coverage(),'u'*64,'h'*64,TARGET,'2026-09-18')
    c=coverage();c['coverage'][0]['latest_date']='2026-09-21'
    with pytest.raises(ValueError,match='BAR_DATE'):
        p.build_o(universe(),c,'u'*64,'h'*64,TARGET)
