"""Model-free intraday sector-rotation Challenger for DSA.

Research-only observation layer. It never changes Champion weights, model prompts,
Top3, trading, schedules, or runtime state. The layer distinguishes a macro Risk-Off
regime from a sector-level Risk-On candidate when hard-tech relative strength is
confirmed across snapshots and evidence channels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Sequence

VERSION = "DSA_INTRADAY_ROTATION_CHALLENGER_v1"


@dataclass(frozen=True)
class Thresholds:
    sector_relative_bps: float = 75.0
    a_share_lead_bps: float = 75.0
    previous_day_relative_bps: float = 75.0
    confirming_snapshots: int = 2
    contrary_evidence_count: int = 2


def evaluate_intraday_rotation(
    *,
    macro_risk_off: bool,
    sector_relative_snapshots_bps: Sequence[Optional[float]],
    a_share_lead_bps: Optional[float],
    previous_day_sector_relative_bps: Optional[float],
    prior_negative_narrative: bool,
    contrary_evidence_count: int,
    thresholds: Thresholds | None = None,
) -> dict:
    """Return a research-only sector-rotation state.

    All numeric thresholds are provisional Challenger defaults, not calibrated
    Champion parameters. Missing critical relative-strength inputs fail closed to
    INSUFFICIENT_EVIDENCE.
    """
    t = thresholds or Thresholds()
    valid_snapshots = [float(v) for v in sector_relative_snapshots_bps if v is not None]
    active = any(v >= t.sector_relative_bps for v in valid_snapshots)

    flags = {
        "intraday_relative_strength": sum(v >= t.sector_relative_bps for v in valid_snapshots) >= t.confirming_snapshots,
        "a_to_h_lead_lag": a_share_lead_bps is not None and float(a_share_lead_bps) >= t.a_share_lead_bps and active,
        "previous_day_persistence": previous_day_sector_relative_bps is not None
        and float(previous_day_sector_relative_bps) >= t.previous_day_relative_bps
        and active,
        "narrative_reversal": bool(prior_negative_narrative)
        and int(contrary_evidence_count) >= t.contrary_evidence_count
        and active,
    }
    confirmations = sum(bool(v) for v in flags.values())

    missing = []
    if not valid_snapshots:
        missing.append("sector_relative_snapshots_bps")
    if a_share_lead_bps is None:
        missing.append("a_share_lead_bps")
    if previous_day_sector_relative_bps is None:
        missing.append("previous_day_sector_relative_bps")

    if missing:
        state = "INSUFFICIENT_EVIDENCE"
    elif macro_risk_off and confirmations >= 3:
        state = "MACRO_DEFENSIVE_SECTOR_RISK_ON_CANDIDATE"
    elif confirmations >= 2:
        state = "SECTOR_STRENGTH_WATCH"
    else:
        state = "NO_OVERRIDE_CANDIDATE"

    return {
        "version": VERSION,
        "state": state,
        "macro_risk_off": bool(macro_risk_off),
        "flags": flags,
        "confirmations": confirmations,
        "critical_missing": missing,
        "thresholds": asdict(t),
        "champion_modified": False,
        "formal_signal_modified": False,
        "top3_modified": False,
        "runtime_activated": False,
        "requires_forward_validation": True,
    }
