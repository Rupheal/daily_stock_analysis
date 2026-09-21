import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

spec=importlib.util.spec_from_file_location("freeze",ROOT/"scripts/freeze_hk_connect_universe.py")
freeze=importlib.util.module_from_spec(spec);spec.loader.exec_module(freeze)

spec2=importlib.util.spec_from_file_location("snap",ROOT/"scripts/dsa_daily_market_snapshot_v1.py")
snap=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(snap)

def test_hkex_identity_label_parses_exact_date():
    assert freeze.parse_hkex_identity_session("Updated as at 18/09/2026")=="2026-09-18"

def test_hkex_identity_bad_header_fails_closed():
    with pytest.raises(ValueError,match="HKEX_IDENTITY_DATE_HEADER_INVALID"):
        freeze.parse_hkex_identity_session("As of 18/09/2026")

def test_daily_snapshot_allows_only_target_and_previous_xhkg_session():
    allowed=snap.identity_sessions_for_daily_snapshot("2026-09-21")
    assert allowed==["2026-09-21","2026-09-18"]
    assert "2026-09-17" not in allowed
    assert "2026-09-22" not in allowed

def test_previous_session_is_identity_only_not_membership_authority():
    allowed=snap.identity_sessions_for_daily_snapshot("2026-09-21")
    assert allowed[-1]=="2026-09-18"
    # Membership itself remains exact-session in freeze(): SSE UPDATE_DATE and SZSE metadata
    # are still required to equal target session; this test locks the intended separation.
    src=(ROOT/"scripts/freeze_hk_connect_universe.py").read_text()
    assert "{r['UPDATE_DATE'] for r in sse}!={session}" in src
    assert "meta['subname']!=session" in src
    assert "'membership_authority':False" in src
