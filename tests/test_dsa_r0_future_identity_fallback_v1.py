import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_r0_probe_scope_exists_and_requires_exact_membership():
    src=(ROOT/"scripts/run_hk_native_data_probe.py").read_text()
    assert "O_r0_membership_data_only" in src
    assert "O R0 requires exact-session verified membership" in src

def test_o_r0_never_claims_formal_full_universe():
    src=(ROOT/"scripts/dsa_daily_o_production_v1.py").read_text()
    assert "'formal_full_universe_claim_permitted':False" in src
    assert "'paid_model_calls':0" in src

def test_u_r0_waits_for_formal_identity_when_macro_exists():
    src=(ROOT/"scripts/dsa_daily_u_production_v1.py").read_text()
    assert "R0_REFRESH_COMPLETE_WAIT_EXACT_IDENTITY_MASTER_FOR_FORMAL" in src

def test_future_hkex_master_is_explicitly_not_used():
    src=(ROOT/"scripts/freeze_hk_connect_universe.py").read_text()
    assert "'used':False" in src
    assert "formal_stock_universe_verified':False" in src
