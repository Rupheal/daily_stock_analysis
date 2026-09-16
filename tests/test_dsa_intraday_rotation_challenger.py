from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsa_intraday_rotation_challenger import Thresholds, evaluate_intraday_rotation


def test_macro_defensive_but_hardtech_risk_on_candidate():
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[90, 130, 160],
        a_share_lead_bps=100,
        previous_day_sector_relative_bps=120,
        prior_negative_narrative=True,
        contrary_evidence_count=3,
    )
    assert out['state'] == 'MACRO_DEFENSIVE_SECTOR_RISK_ON_CANDIDATE'
    assert out['confirmations'] == 4
    assert all(out['flags'].values())
    assert out['champion_modified'] is False
    assert out['formal_signal_modified'] is False


def test_missing_cross_market_data_fails_closed():
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[120, 140],
        a_share_lead_bps=None,
        previous_day_sector_relative_bps=100,
        prior_negative_narrative=True,
        contrary_evidence_count=2,
    )
    assert out['state'] == 'INSUFFICIENT_EVIDENCE'
    assert 'a_share_lead_bps' in out['critical_missing']


def test_single_snapshot_does_not_create_rotation_override():
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[100, 20, 10],
        a_share_lead_bps=20,
        previous_day_sector_relative_bps=20,
        prior_negative_narrative=False,
        contrary_evidence_count=0,
    )
    assert out['state'] == 'NO_OVERRIDE_CANDIDATE'
    assert out['confirmations'] == 0


def test_two_confirmations_only_create_watch_not_macro_override():
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[100, 110],
        a_share_lead_bps=90,
        previous_day_sector_relative_bps=20,
        prior_negative_narrative=False,
        contrary_evidence_count=0,
    )
    assert out['state'] == 'SECTOR_STRENGTH_WATCH'
    assert out['confirmations'] == 2


def test_previous_day_strength_needs_current_confirmation():
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[10, 20],
        a_share_lead_bps=100,
        previous_day_sector_relative_bps=150,
        prior_negative_narrative=True,
        contrary_evidence_count=5,
    )
    assert out['flags']['previous_day_persistence'] is False
    assert out['flags']['a_to_h_lead_lag'] is False
    assert out['flags']['narrative_reversal'] is False


def test_thresholds_are_explicit_and_overridable_for_research_only():
    t = Thresholds(sector_relative_bps=120, a_share_lead_bps=120, previous_day_relative_bps=120)
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[90, 100],
        a_share_lead_bps=100,
        previous_day_sector_relative_bps=100,
        prior_negative_narrative=True,
        contrary_evidence_count=2,
        thresholds=t,
    )
    assert out['state'] == 'NO_OVERRIDE_CANDIDATE'
    assert out['thresholds']['sector_relative_bps'] == 120
    assert out['requires_forward_validation'] is True
