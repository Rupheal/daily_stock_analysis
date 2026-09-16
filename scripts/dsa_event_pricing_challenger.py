"""Research-only event-pricing Challenger for DSA.

Implements a deterministic expectation/surprise framework for scheduled macro events.
It separates what was already priced before an event from target/path surprises and
post-event information effects. It never changes Champion weights, formal signals,
Top3, trading, schedules or runtime state.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional

VERSION = "DSA_EVENT_PRICING_CHALLENGER_v1"


def _validated_distribution(outcomes: Mapping[float, float]) -> dict[float, float]:
    if not outcomes:
        raise ValueError("EMPTY_EVENT_DISTRIBUTION")
    cleaned = {float(k): float(v) for k, v in outcomes.items()}
    if any(v < 0 or not math.isfinite(v) for v in cleaned.values()):
        raise ValueError("INVALID_EVENT_PROBABILITY")
    total = sum(cleaned.values())
    if total <= 0 or abs(total - 1.0) > 1e-6:
        raise ValueError("EVENT_PROBABILITIES_MUST_SUM_TO_ONE")
    return cleaned


def expected_change_bps(outcomes: Mapping[float, float]) -> float:
    dist = _validated_distribution(outcomes)
    return sum(change * prob for change, prob in dist.items())


def normalized_entropy(outcomes: Mapping[float, float]) -> float:
    dist = _validated_distribution(outcomes)
    if len(dist) == 1:
        return 0.0
    raw = -sum(p * math.log(p) for p in dist.values() if p > 0)
    return raw / math.log(len(dist))


def classify_post_event_joint_shock(
    *, two_year_yield_change_bps: Optional[float], equity_change_pct: Optional[float],
    rate_threshold_bps: float = 1.0, equity_threshold_pct: float = 0.15,
) -> str:
    """Classify the rates/equity sign pattern around a narrow event window.

    This is a sign-based research classifier inspired by high-frequency monetary
    policy/event-study literature. It is not a causal proof on a single event.
    """
    if two_year_yield_change_bps is None or equity_change_pct is None:
        return "UNRESOLVED"
    r, e = float(two_year_yield_change_bps), float(equity_change_pct)
    if abs(r) < rate_threshold_bps or abs(e) < equity_threshold_pct:
        return "MUTED_OR_MIXED"
    if r > 0 and e < 0:
        return "HAWKISH_POLICY_SHOCK_CANDIDATE"
    if r < 0 and e > 0:
        return "DOVISH_POLICY_SHOCK_CANDIDATE"
    if r > 0 and e > 0:
        return "POSITIVE_INFORMATION_OR_REACTION_FUNCTION_NEWS_CANDIDATE"
    if r < 0 and e < 0:
        return "NEGATIVE_INFORMATION_OR_GROWTH_NEWS_CANDIDATE"
    return "MUTED_OR_MIXED"


def evaluate_pre_event_pricing(
    *,
    policy_outcomes_bps: Mapping[float, float],
    minutes_until_event: Optional[float],
    path_outcomes_bps: Optional[Mapping[float, float]] = None,
    front_end_yield_change_bps: Optional[float] = None,
    dollar_change_pct: Optional[float] = None,
    equity_change_pct: Optional[float] = None,
    pre_event_equity_move_pct: Optional[float] = None,
    implied_event_move_pct: Optional[float] = None,
) -> dict:
    """Describe how much of a scheduled policy event is already priced.

    The target decision and the future policy path are kept separate. A highly
    concentrated target distribution means the target action is largely priced;
    it does not mean the post-event asset-price direction is known.
    """
    target = _validated_distribution(policy_outcomes_bps)
    target_expected = expected_change_bps(target)
    max_change, max_prob = max(target.items(), key=lambda kv: kv[1])
    target_entropy = normalized_entropy(target)

    if max_prob >= 0.90:
        target_state = "TARGET_OUTCOME_HEAVILY_PRICED"
    elif max_prob >= 0.80:
        target_state = "TARGET_OUTCOME_LARGELY_PRICED"
    elif max_prob >= 0.60:
        target_state = "TARGET_OUTCOME_LEAN"
    else:
        target_state = "TARGET_OUTCOME_DISPERSED"

    path_state = "PATH_DISTRIBUTION_UNAVAILABLE"
    path_entropy = None
    path_expected = None
    if path_outcomes_bps is not None:
        path = _validated_distribution(path_outcomes_bps)
        path_entropy = normalized_entropy(path)
        path_expected = expected_change_bps(path)
        if path_entropy >= 0.50:
            path_state = "PATH_UNCERTAINTY_HIGH"
        elif path_entropy >= 0.25:
            path_state = "PATH_UNCERTAINTY_MATERIAL"
        else:
            path_state = "PATH_RELATIVELY_CONCENTRATED"

    if max_prob >= 0.80 and path_outcomes_bps is None:
        residual_risk = "TARGET_PRICED_PATH_AND_COMMUNICATION_UNRESOLVED"
    elif max_prob >= 0.80 and path_entropy is not None and path_entropy >= 0.25:
        residual_risk = "PATH_AND_COMMUNICATION_DOMINANT"
    else:
        residual_risk = "TARGET_AND_PATH_BOTH_MATERIAL"

    direction = "TIGHTENING" if target_expected > 0 else ("EASING" if target_expected < 0 else "NEUTRAL")
    alignment = {}
    if direction != "NEUTRAL":
        sign = 1 if direction == "TIGHTENING" else -1
        if front_end_yield_change_bps is not None:
            alignment["front_end_rates"] = float(front_end_yield_change_bps) * sign > 0
        if dollar_change_pct is not None:
            alignment["dollar"] = float(dollar_change_pct) * sign > 0
        if equity_change_pct is not None:
            alignment["equity_classical_policy_sign"] = float(equity_change_pct) * sign < 0

    drift_ratio = None
    if pre_event_equity_move_pct is not None and implied_event_move_pct not in (None, 0):
        drift_ratio = abs(float(pre_event_equity_move_pct)) / abs(float(implied_event_move_pct))

    return {
        "version": VERSION,
        "phase": "PRE_EVENT",
        "minutes_until_event": minutes_until_event,
        "target": {
            "expected_change_bps": target_expected,
            "modal_change_bps": max_change,
            "modal_probability": max_prob,
            "normalized_entropy": target_entropy,
            "state": target_state,
        },
        "path": {
            "expected_change_bps": path_expected,
            "normalized_entropy": path_entropy,
            "state": path_state,
        },
        "residual_event_risk": residual_risk,
        "expected_policy_direction": direction,
        "classical_cross_asset_alignment": alignment,
        "pre_event_drift": {
            "equity_move_pct": pre_event_equity_move_pct,
            "implied_event_move_pct": implied_event_move_pct,
            "move_to_implied_ratio": drift_ratio,
            "interpretation": "RISK_PREMIUM_OR_POSITIONING_CONTEXT_ONLY_NOT_PROOF_OF_INFORMATION_LEAK",
        },
        "macro_double_count_guard": max_prob >= 0.80,
        "champion_modified": False,
        "formal_signal_modified": False,
        "top3_modified": False,
        "runtime_activated": False,
        "requires_forward_validation": True,
    }


def evaluate_post_event_surprise(
    *,
    policy_outcomes_bps: Mapping[float, float],
    realized_policy_change_bps: float,
    two_year_yield_change_bps: Optional[float],
    equity_change_pct: Optional[float],
    event_phase: str,
) -> dict:
    expected = expected_change_bps(policy_outcomes_bps)
    surprise = float(realized_policy_change_bps) - expected
    return {
        "version": VERSION,
        "phase": event_phase,
        "target_expected_change_bps": expected,
        "target_realized_change_bps": float(realized_policy_change_bps),
        "target_surprise_bps": surprise,
        "joint_shock_classification": classify_post_event_joint_shock(
            two_year_yield_change_bps=two_year_yield_change_bps,
            equity_change_pct=equity_change_pct,
        ),
        "two_year_yield_change_bps": two_year_yield_change_bps,
        "equity_change_pct": equity_change_pct,
        "champion_modified": False,
        "formal_signal_modified": False,
        "runtime_activated": False,
    }


def event_overlay_for_rotation(event_pricing: Optional[dict]) -> dict:
    """Translate event-pricing state into a research-only macro overlay.

    A priced target decision should not be counted repeatedly as a fresh macro shock.
    Residual path/communication/surprise risk remains live.
    """
    if not event_pricing:
        return {
            "state": "NO_EVENT_CONTEXT",
            "macro_event_double_count_guard": False,
            "residual_event_risk": None,
        }
    guard = bool(event_pricing.get("macro_double_count_guard"))
    return {
        "state": "EXPECTED_TARGET_ALREADY_PRICED_CONTEXT" if guard else "EVENT_EXPECTATION_STILL_DISPERSED",
        "macro_event_double_count_guard": guard,
        "residual_event_risk": event_pricing.get("residual_event_risk"),
        "target_state": (event_pricing.get("target") or {}).get("state"),
        "formal_signal_modified": False,
    }
