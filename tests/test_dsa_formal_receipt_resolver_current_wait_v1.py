import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from dsa_formal_receipt_resolver_v1 import resolve

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj),encoding="utf-8")

def test_resolver_accepts_current_session_o_and_u_wait(tmp_path):
    write(tmp_path/"docs/runtime/O_PRODUCTION_FORMAL_LATEST.json",{
      "status":"PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING",
      "target_session":"2026-09-21",
      "official_O_denominator":660,
      "operational_O_denominator":657,
      "current_session_formal_signals":0,
      "qualified_buy_in_Top3":0,
      "Top3":[]
    })
    write(tmp_path/"docs/runtime/U_PRODUCTION_FORMAL_LATEST.json",{
      "state":"PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
      "target_session":"2026-09-21",
      "denominator":45,
      "formal_valid_rows":0,
      "qualified_BUY":0,
      "Top3":[],
      "rows":[]
    })
    r=resolve(tmp_path,"2026-09-21")
    assert r["state"]=="READY"
    assert r["orchestrator_permitted"] is True
    assert r["O"]["receipt"]["target_session"]=="2026-09-21"
    assert r["U"]["receipt"]["target_session"]=="2026-09-21"

def test_resolver_rejects_relabelled_old_o_top3_wait(tmp_path):
    write(tmp_path/"docs/runtime/O_PRODUCTION_FORMAL_LATEST.json",{
      "status":"PASS_FORMAL_O_DECISION_WAIT_NO_CURRENT_SESSION_RANKING",
      "target_session":"2026-09-21",
      "official_O_denominator":660,
      "operational_O_denominator":657,
      "current_session_formal_signals":0,
      "qualified_buy_in_Top3":0,
      "Top3":[{"code":"00148","rank":1,"action":"HOLD"}]
    })
    write(tmp_path/"docs/runtime/U_PRODUCTION_FORMAL_LATEST.json",{
      "state":"PASS_FORMAL_U_DECISION_WAIT_PREREQ_BLOCKED",
      "target_session":"2026-09-21","denominator":45
    })
    import pytest
    with pytest.raises(ValueError,match="O_MATCHING_RECEIPT_NOT_FORMALLY_USABLE"):
        resolve(tmp_path,"2026-09-21")
