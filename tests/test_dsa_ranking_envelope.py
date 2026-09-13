import json
from pathlib import Path

import pytest

from src.services.dsa_ranking_envelope import build_ranking_envelope

FIXTURE = Path(__file__).parent / "fixtures" / "run004_u_failure_denominator.json"


def real_u45_case():
    data = json.loads(FIXTURE.read_text())
    passed = [row for row in data["coverage"] if row["status"] == "passed_21_observed_daily_bars"]
    isolated = [row for row in data["coverage"] if row["status"] == "isolated"]
    universe = [row["code"] for row in data["coverage"]]
    ranked = [{"code": row["code"], "rank": i + 1} for i, row in enumerate(passed)]
    failures = [{"code": row["code"], "reason": row["reason"]} for row in isolated]
    return data, universe, ranked, failures


def test_real_u45_failure_denominator_is_retained():
    data, universe, ranked, failures = real_u45_case()
    result = build_ranking_envelope(universe, ranked, failures, as_of=data["target"] + "T16:00:00+08:00")
    assert data["denominator"] == 45
    assert len(ranked) == 36 and len(failures) == 9
    assert result["denominator"] == 45
    assert result["ranked"] == 36 and result["isolated"] == 9
    assert result["complete"] is False
    assert result["ranking_order"] == [row["code"] for row in ranked]


def test_partial_real_case_cannot_claim_full_pool_complete():
    data, universe, ranked, failures = real_u45_case()
    with pytest.raises(ValueError, match="partial_coverage"):
        build_ranking_envelope(universe, ranked, failures,
            as_of=data["target"] + "T16:00:00+08:00", claimed_scope="full_pool_complete")


def test_missing_member_cannot_shrink_denominator():
    data, universe, ranked, failures = real_u45_case()
    with pytest.raises(ValueError, match="denominator_mismatch"):
        build_ranking_envelope(universe, ranked[:-1], failures,
            as_of=data["target"] + "T16:00:00+08:00")


def test_duplicate_or_overlap_is_rejected():
    data, universe, ranked, failures = real_u45_case()
    with pytest.raises(ValueError, match="duplicate_ranked"):
        build_ranking_envelope(universe, ranked + [ranked[0]], failures,
            as_of=data["target"] + "T16:00:00+08:00")
    with pytest.raises(ValueError, match="member_in_rank"):
        build_ranking_envelope(universe, ranked, failures + [{"code": ranked[0]["code"], "reason": "conflict"}],
            as_of=data["target"] + "T16:00:00+08:00")


def test_rank_order_must_remain_contiguous():
    data, universe, ranked, failures = real_u45_case()
    ranked[0]["rank"], ranked[1]["rank"] = 2, 1
    with pytest.raises(ValueError, match="contiguous"):
        build_ranking_envelope(universe, ranked, failures,
            as_of=data["target"] + "T16:00:00+08:00")
