import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run056_u_formal_decision as base
import run056_u_formal_decision_prod_v1 as prod

def test_historical_defaults_remain_frozen():
    assert base.TARGET_SESSION=='2026-09-17'
    assert base.EXPECTED_RUN_ID=='TRI-DSA-RESUME-20260917-056'
    assert base.ARTIFACT_PREFIX=='DSA-RUN056-U-FORMAL'

def test_production_config_is_session_scoped(monkeypatch):
    # isolate mutations because prod wrapper intentionally patches module globals
    monkeypatch.setattr(base,'TARGET_SESSION','2026-09-17')
    monkeypatch.setattr(base,'EXPECTED_RUN_ID','TRI-DSA-RESUME-20260917-056')
    monkeypatch.setattr(base,'ARTIFACT_PREFIX','DSA-RUN056-U-FORMAL')
    x=prod.configure('2026-09-18','DSA-U-PROD-20260918')
    assert x['target_session']=='2026-09-18'
    assert base.TARGET_SESSION=='2026-09-18'
    assert base.EXPECTED_RUN_ID=='DSA-U-PROD-20260918'
    assert base.ARTIFACT_PREFIX=='DSA-U-PROD-20260918'
