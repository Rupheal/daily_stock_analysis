import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("r",ROOT/"scripts/dsa_o_cost_value_router_v1.py")
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def test_r0_only_is_default_zero_paid():
    d=r.decide("R0_ONLY",657)
    assert d["paid_model_permitted"] is False
    assert d["paid_member_limit"]==0
    assert d["formal_full_universe_claim_permitted"] is False

def test_calibration_full_allows_full_pool_but_only_at_point_one_cap():
    d=r.decide("CALIBRATION_FULL",657)
    assert d["paid_model_permitted"] is True
    assert d["paid_member_limit"]==657
    assert d["per_member_cap_cny"]=="0.10"
    assert d["session_hard_ceiling_cny"]=="65.70"

def test_selective_fails_closed_without_accepted_calibration():
    d=r.decide("SELECTIVE",657,{"status":"DRAFT"})
    assert d["paid_model_permitted"] is False
    assert d["reason"]=="SELECTIVE_ROUTER_NOT_CALIBRATED"

def test_selective_accepts_only_explicit_calibrated_limit():
    d=r.decide("SELECTIVE",657,{"status":"ACCEPTED_SELECTIVE_ROUTER","calibration_id":"x","paid_member_limit":80})
    assert d["paid_model_permitted"] is True
    assert d["paid_member_limit"]==80
    assert d["formal_full_universe_claim_permitted"] is False
