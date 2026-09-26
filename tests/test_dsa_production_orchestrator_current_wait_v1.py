import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from dsa_production_orchestrator_v1 import classify_o,classify_u,orchestrate

TARGET="2026-09-21"
NEXT="2026-09-22"
NOW="2026-09-21T16:35:00+08:00"

def o_wait():
    return {
      "status":"PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING",
      "target_session":TARGET,
      "signal_timing":{"cutoff":"2026-09-21T16:00:00+08:00","available_at":"2026-09-21T16:32:37+08:00",
                       "valid_until":"2026-09-25T16:32:37+08:00","next_session":NEXT},
      "official_O_denominator":660,
      "operational_O_denominator":657,
      "current_session_formal_signals":0,
      "qualified_buy_in_Top3":0,
      "Top3":[],
      "Top10":[]
    }

def u_wait():
    return {
      "state":"PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
      "target_session":TARGET,
      "signal_timing":{"cutoff":"2026-09-21T16:00:00+08:00","available_at":"2026-09-21T16:32:37+08:00",
                       "valid_until":"2026-09-25T16:32:37+08:00","next_session":NEXT},
      "denominator":45,
      "formal_valid_rows":0,
      "qualified_BUY":0,
      "Top3":[],
      "rows":[],
      "prerequisite_blockers":[
        "U_CURRENT_SESSION_MACRO_CAP_MISSING",
        "U_CURRENT_SESSION_RISK_EVIDENCE_MISSING",
        "U_CURRENT_SESSION_ZONE_CONTRACT_MISSING"
      ]
    }

def test_explicit_o_current_session_wait_is_wait_not_blocked():
    r=classify_o(o_wait(),TARGET)
    assert r["state"]=="WAIT"
    assert r["qualified_buy"]==0
    assert r["blockers"]==[]

def test_explicit_u_prereq_wait_is_wait_not_blocked():
    r=classify_u(u_wait(),TARGET)
    assert r["state"]=="WAIT"
    assert r["qualified_buy"]==0
    assert r["blockers"]==[]

def test_current_session_dual_wait_orchestrates_to_wait_no_buy(tmp_path):
    op=tmp_path/"o.json";up=tmp_path/"u.json"
    import json
    op.write_text(json.dumps(o_wait()));up.write_text(json.dumps(u_wait()))
    r=orchestrate(o_wait(),u_wait(),TARGET,NOW,NEXT,op,up,None,False,"postclose")
    assert r["state"]=="WAIT_NO_BUY"
    assert r["tracks"]["O"]["state"]=="WAIT"
    assert r["tracks"]["U"]["state"]=="WAIT"
    assert r["qualified_buy_total"]==0
    assert r["real_orders"]==0
    assert len(r["commands"])==2
    assert all(x["kind"]=="SIGNAL" and x["signal"]["passed"] is False for x in r["commands"])
