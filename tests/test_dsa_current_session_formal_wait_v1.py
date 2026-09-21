import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from dsa_current_session_formal_wait_v1 import build,O_WAIT,U_WAIT

def evidence():
    return {
      "target_session":"2026-09-21",
      "source":{"repository":"Rupheal/TRIDENT-Foundation","branch":"runtime/dsa-shadow-journal-v1","journal_path":"j","journal_blob_sha":"b"},
      "O":{
        "preopen":{"command_id":"op","wrapper_hash":"a"*64,"at":"2026-09-21T09:01:46+08:00","current_session_formal_signals":0,"latest_accepted_target_session":"2026-09-18","latest_qualified_BUY":0,"official_denominator":660,"operational_denominator":657},
        "close":{"command_id":"oc","wrapper_hash":"b"*64,"at":"2026-09-21T16:32:37+08:00","current_session_formal_signals":0,"latest_accepted_target_session":"2026-09-18","latest_qualified_BUY":0,"official_denominator":660,"operational_denominator":657},
        "prior_reference":{"target_session":"2026-09-18"}
      },
      "U":{
        "preopen":{"command_id":"up","wrapper_hash":"c"*64,"at":"2026-09-21T09:01:46+08:00","current_session_formal_signals":0,"latest_accepted_target_session":"2026-09-18","latest_qualified_BUY":0,"denominator":45,"current_session_blockers":["U_CURRENT_SESSION_MACRO_CAP_MISSING","U_CURRENT_SESSION_RISK_EVIDENCE_MISSING","U_CURRENT_SESSION_ZONE_CONTRACT_MISSING"]},
        "close":{"command_id":"uc","wrapper_hash":"d"*64,"at":"2026-09-21T16:32:37+08:00","current_session_formal_signals":0,"latest_accepted_target_session":"2026-09-18","latest_qualified_BUY":0,"denominator":45},
        "prior_reference":{"target_session":"2026-09-18"}
      },
      "safety":{"model_http_requests_confirmed":0,"real_orders":0,"simulation_writes":0,"auto_recharge":False}
    }

def test_builds_session_correct_authoritative_waits():
    o,u,a=build(evidence(),"2026-09-21")
    assert o["status"]==O_WAIT and o["target_session"]=="2026-09-21"
    assert o["Top3"]==[] and o["qualified_buy_in_Top3"]==0
    assert u["state"]==U_WAIT and u["target_session"]=="2026-09-21"
    assert u["prerequisite_blockers"]
    assert a["status"]=="ACCEPTED_CURRENT_SESSION_FORMAL_WAIT"
    assert a["prior_session_rankings_not_relabelled"] is True
    assert a["resource_accounting"]["model_http_requests_confirmed"]==0
    assert a["resource_accounting"]["real_orders"]==0

def test_rejects_any_current_session_formal_signal():
    e=evidence();e["O"]["close"]["current_session_formal_signals"]=1
    with pytest.raises(ValueError,match="O_CURRENT_SESSION_FORMAL_SIGNAL_NONZERO"):
        build(e,"2026-09-21")

def test_rejects_nonzero_buy():
    e=evidence();e["U"]["close"]["latest_qualified_BUY"]=1
    with pytest.raises(ValueError,match="U_LATEST_QUALIFIED_BUY_NONZERO"):
        build(e,"2026-09-21")

def test_rejects_wrong_u_blocker_set():
    e=evidence();e["U"]["preopen"]["current_session_blockers"]=[]
    with pytest.raises(ValueError,match="U_CURRENT_SESSION_BLOCKERS_MISMATCH"):
        build(e,"2026-09-21")
