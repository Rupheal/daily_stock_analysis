"""Build a bounded historical SSE Southbound universe by reversing an official later adjustment.

This is an effective-date reconstruction artifact, NOT proof that the reconstructed list
was itself archived/available to the model at the historical decision timestamp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(value) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8"))


def code5(value) -> str:
    return str(value).upper().removeprefix("HK").removesuffix(".HK").zfill(5)


def build(anchor_path: Path, adjustment_path: Path, output_path: Path, decision_session: str):
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    adj = json.loads(adjustment_path.read_text(encoding="utf-8"))
    if anchor.get("member_count") != len(anchor.get("members") or []):
        raise ValueError("anchor_denominator_mismatch")
    if adj.get("additions_count") != len(adj.get("additions") or []) or adj.get("removals_count") != len(adj.get("removals") or []):
        raise ValueError("adjustment_count_mismatch")
    if adj.get("governance", {}).get("pit_input_admissible_at_2026_09_03") is not False:
        raise ValueError("later_adjustment_must_not_be_pit_input")

    by_code = {code5(row["code"]): dict(row) for row in anchor["members"]}
    if len(by_code) != len(anchor["members"]):
        raise ValueError("duplicate_anchor_code")
    current_sse = {c for c, row in by_code.items() if "SSE" in (row.get("channels") or [])}
    additions = {code5(c) for c in adj["additions"]}
    removals = {code5(c) for c in adj["removals"]}
    if additions & removals:
        raise ValueError("adjustment_overlap")
    missing_future_additions = sorted(additions - current_sse)
    if missing_future_additions:
        raise ValueError("anchor_missing_post_adjustment_sse_members:" + ",".join(missing_future_additions))
    still_sse_removed = sorted(removals & current_sse)
    if still_sse_removed:
        raise ValueError("anchor_still_contains_removed_sse_members:" + ",".join(still_sse_removed))

    historical = (current_sse - additions) | removals
    members = []
    for c in sorted(historical):
        row = by_code.get(c)
        members.append({
            "code": c,
            "official_name": (row or {}).get("official_name", ""),
            "english_name": (row or {}).get("english_name", ""),
            "security_type": (row or {}).get("security_type", "股票"),
            "historical_channel": "SSE",
            "reconstruction_provenance": "anchor_member" if c in current_sse else "restored_from_official_2026_09_04_removal"
        })

    member_hash = canonical_hash([m["code"] for m in members])
    result = {
        "schema_version": 1,
        "universe_id": f"SSE_SOUTHBOUND_{decision_session}_EFFECTIVE_RECONSTRUCTED",
        "decision_session": decision_session,
        "scope": "SSE_SOUTHBOUND_ONLY",
        "member_count": len(members),
        "members": members,
        "effective_date_reconstruction": {
            "anchor_universe_id": anchor.get("universe_id"),
            "anchor_effective_session": anchor.get("effective_session"),
            "anchor_observed_at_utc": anchor.get("observed_at_utc"),
            "anchor_file_sha256": file_sha256(anchor_path),
            "later_adjustment_file_sha256": file_sha256(adjustment_path),
            "later_adjustment_source_url": adj.get("source_url"),
            "later_notice_id": adj.get("notice_id"),
            "later_notice_published_date": adj.get("published_date"),
            "reversed_additions": len(additions),
            "restored_removals": len(removals),
            "current_sse_anchor_count": len(current_sse)
        },
        "future_leakage_checks": {
            "all_2026_09_04_additions_excluded": additions.isdisjoint(historical),
            "all_2026_09_04_removals_restored": removals.issubset(historical),
            "later_notice_used_as_model_input": False
        },
        "member_codes_sha256": member_hash,
        "reconstruction_status": "AFTER_THE_FACT_EFFECTIVE_DATE_RECONSTRUCTION",
        "pit_input_admissibility": "WAIT_ARCHIVED_AS_AVAILABLE_THEN_UNIVERSE_EVIDENCE",
        "governance_note": "This artifact may establish historical effective membership by rollback. It must not be passed as PIT-admissible model input until an archived/list evidence source demonstrably available by the historical decision timestamp is attached."
    }
    if not all(result["future_leakage_checks"][k] for k in ("all_2026_09_04_additions_excluded", "all_2026_09_04_removals_restored")):
        raise ValueError("future_membership_leakage")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anchor", type=Path, required=True)
    p.add_argument("--adjustment", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--decision-session", default="2026-09-03")
    return p


if __name__ == "__main__":
    args=parser().parse_args()
    result=build(args.anchor,args.adjustment,args.output,args.decision_session)
    print("RUN004_SSE_PIT_RECON", json.dumps({
        "universe_id": result["universe_id"],
        "member_count": result["member_count"],
        "member_codes_sha256": result["member_codes_sha256"],
        "pit_input_admissibility": result["pit_input_admissibility"]
    }, ensure_ascii=False))
