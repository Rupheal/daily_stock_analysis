"""Deterministic denominator accounting around DSA rankings.

The envelope never creates model scores. It prevents partial/failed coverage from
being presented as a complete full-pool ranking by retaining every universe member.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _code(value):
    text = str(value).upper().removeprefix("HK").removesuffix(".HK")
    return "HK" + text.zfill(5)


def build_ranking_envelope(universe_codes, ranked_rows, isolated_rows, *, as_of,
                           claimed_scope="partial_with_isolations"):
    datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    universe = [_code(code) for code in universe_codes]
    if len(set(universe)) != len(universe):
        raise ValueError("duplicate_universe_member")
    ranked = [dict(row, code=_code(row["code"])) for row in ranked_rows]
    isolated = [dict(row, code=_code(row["code"])) for row in isolated_rows]
    ranked_codes = [row["code"] for row in ranked]
    isolated_codes = [row["code"] for row in isolated]
    if len(set(ranked_codes)) != len(ranked_codes):
        raise ValueError("duplicate_ranked_member")
    if len(set(isolated_codes)) != len(isolated_codes):
        raise ValueError("duplicate_isolated_member")
    if set(ranked_codes) & set(isolated_codes):
        raise ValueError("member_in_rank_and_isolation")
    accounted = set(ranked_codes) | set(isolated_codes)
    missing = sorted(set(universe) - accounted)
    extra = sorted(accounted - set(universe))
    if missing or extra:
        raise ValueError(f"denominator_mismatch:missing={missing}:extra={extra}")
    ranks = [row.get("rank") for row in ranked]
    if ranks != list(range(1, len(ranked) + 1)):
        raise ValueError("ranking_must_be_contiguous_and_preserve_order")
    if any(not str(row.get("reason") or "").strip() for row in isolated):
        raise ValueError("isolated_member_requires_reason")
    if claimed_scope == "full_pool_complete" and isolated:
        raise ValueError("partial_coverage_cannot_be_full_pool_complete")
    if claimed_scope not in ("full_pool_complete", "partial_with_isolations"):
        raise ValueError("invalid_claimed_scope")
    result = {
        "as_of": as_of,
        "denominator": len(universe),
        "ranked": len(ranked),
        "isolated": len(isolated),
        "claimed_scope": claimed_scope,
        "complete": not isolated,
        "ranking_order": ranked_codes,
        "isolations": isolated,
    }
    result["accounting_sha256"] = canonical_hash(result)
    return result
