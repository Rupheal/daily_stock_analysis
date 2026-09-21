import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("r",ROOT/"scripts/u_daily_risk_evidence_v1.py")
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

T="2026-09-21"
def uni():
    return {"members":[{"code":f"{i:05d}","channels":["SSE"],"execution_eligibility":"verified_current_buy_sell","official_name":f"N{i}"} for i in range(1,46)]}
def mem():
    return {"target_session":T,"members":[{"code":f"{i:05d}","data_session":T,"status":"PRODUCTION_TECHNICAL_FACT_REPORT","facts":{"close":10+i}} for i in range(1,46)]}
def cap():
    return {"sources":[{"data":{"top10_union":{"00001":{"status":"VERIFIED","net_buy_hkd":"100","channel_coverage":2}}}}]}
def macro():
    return {"target_session":T,"regime":{"position_ceiling_pct":30},"result":{"formal_macro_cap_available":True}}

def test_current_risk_packet_uses_current_inputs_and_preserves_missingness():
    out=r.build(uni(),mem(),cap(),macro(),T)
    assert out["counts"]["eligible"]==45
    assert out["counts"]["capital_verified"]==1
    assert out["counts"]["formal_decision_input_pass_with_missingness"]==45
    assert out["rows"][0]["capital_evidence"]["state"]=="VERIFIED"
    assert out["rows"][1]["capital_evidence"]["state"]=="NOT_DISCLOSED_IN_TOP10"
    assert out["result"]["qualified_BUY_created"]==0

def test_stale_macro_fails_closed():
    m=macro();m["target_session"]="2026-09-18"
    try:r.build(uni(),mem(),cap(),m,T)
    except ValueError as e:assert "SESSION_MISMATCH" in str(e)
    else:assert False
