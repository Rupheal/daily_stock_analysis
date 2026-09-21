import importlib.util, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("guard",ROOT/"scripts/dsa_daily_formal_generation_guard_v1.py")
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
sys.path.insert(0,str(ROOT/"scripts"))
import dsa_production_orchestrator_v1 as orch

TARGET="2026-09-21"

def o_fallback():
    return {"target_session":TARGET,"status":"PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING",
            "official_O_denominator":660,"operational_O_denominator":657,
            "current_session_formal_signals":0,"qualified_buy_in_Top3":0,"Top3":[]}

def u_fallback():
    return {"target_session":TARGET,"state":"PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
            "denominator":45,"formal_valid_rows":0,"qualified_BUY":0,"Top3":[],"rows":[],
            "provider_skipped":True,
            "prerequisite_blockers":["U_CURRENT_SESSION_MACRO_CAP_MISSING"]}

def o_buy():
    return {"target_session":TARGET,"status":"ACCEPTED_O_FORMAL_TOP3",
            "official_O_denominator":660,"operational_O_denominator":657,
            "ranking_eligible_count":356,"missing_count":0,"qualified_buy_in_Top3":1,
            "Top3":[{"code":"00700","rank":1,"sentiment_score":88,"action":"buy",
                     "action_family":"buy","industry":"Internet","buyable_verified":True}]}

def u_buy():
    row={"code":"00992","rank":1,"score":82,"formal_action":"BUY","industry":"Auto",
         "buyable_verified":True,"validation":"PASS","zone_status":"APPROVED_NUMERIC",
         "zone_lower_hkd":95.0,"zone_upper_hkd":100.0,"macro_position_ceiling_pct":30}
    return {"target_session":TARGET,"state":"PASS_FORMAL_U_DECISION_WITH_BUYS",
            "denominator":45,"formal_valid_rows":44,"qualified_BUY":1,
            "Top3":[{"code":"00992","rank":1,"score":82,"formal_action":"BUY","industry":"Auto"}],
            "rows":[row],"provider_skipped":False}

def entry(code):
    return {"code":code,"at":"2026-09-22T09:36:00+08:00","price":"99.0","cny_per_hkd":"0.92",
            "lot_size":100,"fee_cny":"5","source":"fixture","sha256":"a"*64,
            "fx_source":"fixture-fx","fx_sha256":"b"*64,"fx_at":"2026-09-22T09:36:00+08:00",
            "session":"2026-09-22","tradable":True,"first_eligible_price_verified":True,
            "lot_verified":True}

def test_fallback_wait_is_not_generation_complete():
    r=g.assess_pair(o_fallback(),u_fallback(),TARGET)
    assert r["state"]=="WAIT_DAILY_FORMAL_GENERATION"
    assert r["O"]["state"]=="MISSING_GENERATION"
    assert r["U"]["state"]=="MISSING_GENERATION"
    assert r["entry_evaluation_permitted"] is False

def test_generated_no_buy_is_distinct_from_missing_generation():
    o=o_buy(); o["qualified_buy_in_Top3"]=0; o["Top3"][0]["action"]="hold"; o["Top3"][0]["action_family"]="hold"
    u=u_buy(); u["qualified_BUY"]=0; u["Top3"]=[]; u["rows"][0]["formal_action"]="WATCH"; u["rows"][0]["buyable_verified"]=False
    r=g.assess_pair(o,u,TARGET)
    assert r["generation_complete"] is True
    assert r["state"]=="READY_FOR_ENTRY_EVALUATION"

def test_o_valid_buy_fixture_reaches_entry_gate(tmp_path):
    o=o_buy()
    t=orch.classify_o(o,TARGET)
    assert t["state"]=="QUALIFIED_BUY" and t["qualified_buy"]==1
    p=tmp_path/"o.json";p.write_text(json.dumps(o))
    sig=orch.build_signal(t,p,"2026-09-22T09:35:00+08:00","2026-09-22","2026-09-26T09:35:00+08:00")
    entries,blocks=orch.build_entry(t,sig,entry("00700"))
    assert blocks==[]
    assert len(entries)==1 and entries[0]["code"]=="00700"

def test_u_valid_buy_fixture_reaches_entry_gate(tmp_path):
    u=u_buy()
    t=orch.classify_u(u,TARGET)
    assert t["state"]=="QUALIFIED_BUY" and t["qualified_buy"]==1
    p=tmp_path/"u.json";p.write_text(json.dumps(u))
    sig=orch.build_signal(t,p,"2026-09-22T09:35:00+08:00","2026-09-22","2026-09-26T09:35:00+08:00")
    entries,blocks=orch.build_entry(t,sig,entry("00992"))
    assert blocks==[]
    assert len(entries)==1 and entries[0]["code"]=="00992"

def test_u_approved_numeric_is_accepted_by_orchestrator():
    u=u_buy()
    t=orch.classify_u(u,TARGET)
    assert t["blockers"]==[]
    assert t["state"]=="QUALIFIED_BUY"
    assert t["candidates"][0]["zone_status"]=="APPROVED_NUMERIC"
