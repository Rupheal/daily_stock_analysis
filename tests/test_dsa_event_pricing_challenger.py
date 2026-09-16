from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dsa_event_pricing_challenger import (
    classify_post_event_joint_shock,
    event_overlay_for_rotation,
    evaluate_post_event_surprise,
    evaluate_pre_event_pricing,
    expected_change_bps,
    normalized_entropy,
)
from dsa_intraday_rotation_challenger import evaluate_intraday_rotation


def test_expected_change_uses_probability_weighted_target():
    assert expected_change_bps({0: 0.075, 25: 0.925}) == 23.125


def test_concentrated_target_is_heavily_priced_but_path_unresolved():
    out = evaluate_pre_event_pricing(
        policy_outcomes_bps={0: 0.075, 25: 0.925},
        minutes_until_event=250,
        front_end_yield_change_bps=8,
        dollar_change_pct=0.4,
    )
    assert out['target']['state'] == 'TARGET_OUTCOME_HEAVILY_PRICED'
    assert out['macro_double_count_guard'] is True
    assert out['residual_event_risk'] == 'TARGET_PRICED_PATH_AND_COMMUNICATION_UNRESOLVED'
    assert out['expected_policy_direction'] == 'TIGHTENING'
    assert out['classical_cross_asset_alignment']['front_end_rates'] is True
    assert out['classical_cross_asset_alignment']['dollar'] is True


def test_distributed_target_is_not_double_count_guarded():
    out = evaluate_pre_event_pricing(
        policy_outcomes_bps={-25: 0.34, 0: 0.33, 25: 0.33},
        minutes_until_event=300,
    )
    assert out['target']['state'] == 'TARGET_OUTCOME_DISPERSED'
    assert out['macro_double_count_guard'] is False


def test_path_distribution_stays_separate_from_target_distribution():
    out = evaluate_pre_event_pricing(
        policy_outcomes_bps={0: 0.05, 25: 0.95},
        path_outcomes_bps={25: 0.25, 50: 0.35, 75: 0.25, 100: 0.15},
        minutes_until_event=120,
    )
    assert out['target']['state'] == 'TARGET_OUTCOME_HEAVILY_PRICED'
    assert out['path']['state'] in {'PATH_UNCERTAINTY_MATERIAL', 'PATH_UNCERTAINTY_HIGH'}
    assert out['residual_event_risk'] == 'PATH_AND_COMMUNICATION_DOMINANT'


def test_pre_event_drift_is_context_not_information_leak_claim():
    out = evaluate_pre_event_pricing(
        policy_outcomes_bps={0: 0.1, 25: 0.9},
        minutes_until_event=180,
        pre_event_equity_move_pct=0.6,
        implied_event_move_pct=1.2,
    )
    assert out['pre_event_drift']['move_to_implied_ratio'] == 0.5
    assert 'NOT_PROOF_OF_INFORMATION_LEAK' in out['pre_event_drift']['interpretation']


def test_joint_shock_sign_classifier_separates_policy_and_information_candidates():
    assert classify_post_event_joint_shock(two_year_yield_change_bps=6, equity_change_pct=-0.8) == 'HAWKISH_POLICY_SHOCK_CANDIDATE'
    assert classify_post_event_joint_shock(two_year_yield_change_bps=-5, equity_change_pct=0.7) == 'DOVISH_POLICY_SHOCK_CANDIDATE'
    assert classify_post_event_joint_shock(two_year_yield_change_bps=5, equity_change_pct=0.7) == 'POSITIVE_INFORMATION_OR_REACTION_FUNCTION_NEWS_CANDIDATE'
    assert classify_post_event_joint_shock(two_year_yield_change_bps=-5, equity_change_pct=-0.7) == 'NEGATIVE_INFORMATION_OR_GROWTH_NEWS_CANDIDATE'


def test_post_event_surprise_compares_realized_with_pre_event_expectation():
    out = evaluate_post_event_surprise(
        policy_outcomes_bps={0: 0.2, 25: 0.8},
        realized_policy_change_bps=25,
        two_year_yield_change_bps=4,
        equity_change_pct=-0.5,
        event_phase='STATEMENT_WINDOW',
    )
    assert out['target_expected_change_bps'] == 20.0
    assert out['target_surprise_bps'] == 5.0
    assert out['joint_shock_classification'] == 'HAWKISH_POLICY_SHOCK_CANDIDATE'


def test_rotation_overlay_does_not_change_confirmation_count_or_formal_signal():
    event = evaluate_pre_event_pricing(
        policy_outcomes_bps={0: 0.075, 25: 0.925},
        minutes_until_event=250,
    )
    out = evaluate_intraday_rotation(
        macro_risk_off=True,
        sector_relative_snapshots_bps=[100, 120],
        a_share_lead_bps=90,
        previous_day_sector_relative_bps=20,
        prior_negative_narrative=False,
        contrary_evidence_count=0,
        event_pricing_context=event,
    )
    assert out['confirmations'] == 2
    assert out['state'] == 'SECTOR_STRENGTH_WATCH'
    assert out['event_pricing_overlay']['macro_event_double_count_guard'] is True
    assert out['formal_signal_modified'] is False


def test_invalid_probability_distribution_fails_closed():
    try:
        evaluate_pre_event_pricing(policy_outcomes_bps={0: 0.5, 25: 0.6}, minutes_until_event=10)
    except ValueError as exc:
        assert str(exc) == 'EVENT_PROBABILITIES_MUST_SUM_TO_ONE'
    else:
        raise AssertionError('invalid distribution must fail')


def test_entropy_is_zero_for_certain_single_outcome():
    assert normalized_entropy({25: 1.0}) == 0.0
