import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("m",ROOT/"scripts/u_production_daily_member_v1.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_yahoo_hk_ticker_is_four_digit_not_five_digit():
    assert m.yahoo_ticker("00700")=="0700.HK"
    assert m.yahoo_ticker("00005")=="0005.HK"
    assert m.yahoo_ticker("00992")=="0992.HK"
    assert m.yahoo_ticker("06166")=="6166.HK"

def test_u_daily_status_cannot_claim_complete_with_zero_rows():
    src=(ROOT/"scripts/dsa_daily_u_production_v1.py").read_text()
    assert "member_ready==45 and close_ready==45" in src
    assert "R0_REFRESH_PARTIAL_DATA" in src
