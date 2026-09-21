#!/usr/bin/env python3
"""Read-only Candidate Adapter for the DSA Production Orchestrator.

The adapter never changes O/U receipts, never creates BUY decisions, and never
writes an Authority ledger. It validates frozen governance pointers, interprets
formal O/U receipts deterministically, and compares that interpretation with the
existing Production Orchestrator classifiers. Optional output is a bounded
Parallel Shadow receipt only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VERSION = "DSA_CANDIDATE_ADAPTER_v1"


class CandidateAdapterError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def _inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CandidateAdapterError("PATH_ESCAPE", str(path)) from exc
    return resolved


def _read_json(path: Path, label: str) -> tuple[dict, bytes]:
    if not path.exists():
        raise CandidateAdapterError(f"MISSING_{label}", str(path))
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except Exception as exc:
        raise CandidateAdapterError(f"INVALID_JSON_{label}", str(path)) from exc
    if not isinstance(value, dict):
        raise CandidateAdapterError(f"INVALID_OBJECT_{label}", str(path))
    return value, data


def _verify_source(root: Path, spec: dict, label: str) -> tuple[dict, dict]:
    rel = spec.get("path")
    expected_blob = spec.get("git_blob_sha1")
    if not rel or not expected_blob:
        raise CandidateAdapterError(f"POINTER_INCOMPLETE_{label}")
    path = _inside(root, root / rel)
    obj, data = _read_json(path, label)
    actual_blob = _git_blob_sha1(data)
    if actual_blob != expected_blob:
        raise CandidateAdapterError(
            f"HASH_DRIFT_{label}", f"expected={expected_blob} actual={actual_blob}"
        )
    return obj, {
        "path": rel,
        "git_blob_sha1": actual_blob,
        "sha256": _sha256(data),
        "bytes": len(data),
    }


def _verify_text_source(root: Path, spec: dict, label: str) -> dict:
    rel = spec.get("path")
    expected_blob = spec.get("git_blob_sha1")
    if not rel or not expected_blob:
        raise CandidateAdapterError(f"POINTER_INCOMPLETE_{label}")
    path = _inside(root, root / rel)
    if not path.exists():
        raise CandidateAdapterError(f"MISSING_{label}", str(path))
    data = path.read_bytes()
    actual_blob = _git_blob_sha1(data)
    if actual_blob != expected_blob:
        raise CandidateAdapterError(
            f"HASH_DRIFT_{label}", f"expected={expected_blob} actual={actual_blob}"
        )
    return {
        "path": rel,
        "git_blob_sha1": actual_blob,
        "sha256": _sha256(data),
        "bytes": len(data),
    }


def _norm_action(value) -> str:
    return str(value or "").strip().upper()


def _o_candidates(receipt: dict) -> list[dict]:
    rows = []
    for x in receipt.get("Top3") or []:
        action = _norm_action(x.get("action"))
        family = str(x.get("action_family") or "").lower()
        buy = action == "BUY" or family == "buy"
        rows.append({
            "code": str(x.get("code") or ""),
            "rank": x.get("rank"),
            "score": x.get("sentiment_score"),
            "industry": x.get("industry"),
            "action": "BUY" if buy else action,
            "buyable_verified": bool(x.get("buyable_verified")) if buy else False,
        })
    return rows


def _u_candidates(receipt: dict) -> list[dict]:
    by_code = {str(x.get("code")): x for x in receipt.get("rows") or []}
    rows = []
    for x in receipt.get("Top3") or []:
        code = str(x.get("code") or "")
        src = by_code.get(code, {})
        action = _norm_action(x.get("formal_action") or src.get("formal_action"))
        rows.append({
            "code": code,
            "rank": x.get("rank") or src.get("rank"),
            "score": x.get("score") if x.get("score") is not None else src.get("score"),
            "industry": x.get("industry") or src.get("industry"),
            "action": action,
            "buyable_verified": bool(src.get("buyable_verified")),
            "zone_status": src.get("zone_status"),
            "zone_lower_hkd": src.get("zone_lower_hkd"),
            "zone_upper_hkd": src.get("zone_upper_hkd"),
            "validation": src.get("validation"),
            "macro_position_ceiling_pct": src.get("macro_position_ceiling_pct"),
        })
    return rows


def _interpret_o(receipt: dict, target_session: str) -> dict:
    blockers = []
    if int(receipt.get("missing_count", -1)) != 0:
        blockers.append("O_MISSING_NOT_ZERO")
    candidates = _o_candidates(receipt)
    claimed = int(receipt.get("qualified_buy_in_Top3", 0) or 0)
    buys = [x for x in candidates if x["action"] == "BUY"]
    if claimed != len(buys):
        blockers.append("O_QUALIFIED_BUY_COUNT_MISMATCH")
    for x in buys:
        if not x["code"] or x["rank"] not in (1, 2, 3) or x["score"] is None:
            blockers.append("O_BUY_CORE_FIELDS_MISSING")
        if not x["buyable_verified"]:
            blockers.append("O_BUYABILITY_NOT_VERIFIED")
        if not x["industry"]:
            x["industry"] = "UNCLASSIFIED"
    state = "BLOCKED" if blockers else "QUALIFIED_BUY" if buys else "WAIT"
    return {
        "track": "O",
        "state": state,
        "session": target_session,
        "target_session": target_session,
        "qualified_buy": len(buys),
        "candidates": candidates,
        "blockers": sorted(set(blockers)),
    }


def _interpret_u(receipt: dict, target_session: str) -> dict:
    blockers = []
    if int(receipt.get("denominator", -1)) != 45:
        blockers.append("U_DENOMINATOR_NOT_45")
    if int(receipt.get("formal_valid_rows", -1)) < 1:
        blockers.append("U_NO_FORMAL_ROWS")
    candidates = _u_candidates(receipt)
    claimed = int(receipt.get("qualified_BUY", 0) or 0)
    buys = [x for x in candidates if x["action"] == "BUY"]
    if claimed != len(buys):
        blockers.append("U_QUALIFIED_BUY_COUNT_MISMATCH")
    for x in buys:
        if not x["code"] or x["rank"] not in (1, 2, 3) or x["score"] is None:
            blockers.append("U_BUY_CORE_FIELDS_MISSING")
        if not x["buyable_verified"] or x.get("validation") != "PASS":
            blockers.append("U_BUYABILITY_NOT_VERIFIED")
        if not x["industry"]:
            x["industry"] = "UNCLASSIFIED"
        if x.get("zone_status") not in {"APPROVED", "VERIFIED", "PASS", "FORMAL_APPROVED"}:
            blockers.append("U_BUY_ZONE_NOT_APPROVED")
        if x.get("zone_lower_hkd") is None or x.get("zone_upper_hkd") is None:
            blockers.append("U_BUY_ZONE_MISSING")
        if x.get("macro_position_ceiling_pct") is None:
            blockers.append("U_MACRO_CAP_MISSING")
    state = "BLOCKED" if blockers else "QUALIFIED_BUY" if buys else "WAIT"
    return {
        "track": "U",
        "state": state,
        "session": target_session,
        "target_session": target_session,
        "qualified_buy": len(buys),
        "candidates": candidates,
        "blockers": sorted(set(blockers)),
    }


def _projection(track: dict) -> dict:
    fields = ("code", "rank", "score", "industry", "action", "buyable_verified")
    return {
        "track": track.get("track"),
        "state": track.get("state"),
        "session": track.get("session"),
        "target_session": track.get("target_session"),
        "qualified_buy": track.get("qualified_buy"),
        "blockers": track.get("blockers") or [],
        "candidates": [{k: x.get(k) for k in fields} for x in track.get("candidates") or []],
    }


def _validate_denominators(o: dict, u: dict, pointer: dict) -> dict:
    ospec = pointer["sources"]["O"]
    uspec = pointer["sources"]["U"]
    official = int(o.get("official_O_denominator", -1))
    operational = int(o.get("operational_O_denominator", -1))
    base_excl = int(o.get("base_excluded_count", -1))
    additional_excl = int(o.get("additional_excluded_count", -1))
    ranked = int(o.get("ranking_eligible_count", -1))
    if official != int(ospec.get("official_denominator", -2)):
        raise CandidateAdapterError("DENOMINATOR_MISMATCH_O_OFFICIAL")
    if operational != int(ospec.get("operational_denominator", -2)):
        raise CandidateAdapterError("DENOMINATOR_MISMATCH_O_OPERATIONAL")
    if operational + base_excl != official or ranked + additional_excl != operational:
        raise CandidateAdapterError("DENOMINATOR_EQUATION_O")
    if int(u.get("denominator", -1)) != int(uspec.get("denominator", -2)):
        raise CandidateAdapterError("DENOMINATOR_MISMATCH_U")
    return {
        "O": {
            "official_denominator": official,
            "operational_denominator": operational,
            "formal_acceptance_denominator": ranked,
            "base_exclusions": base_excl,
            "operational_exclusions": additional_excl,
            "explicit_exclusions_total": base_excl + additional_excl,
            "equation_official": ranked + base_excl + additional_excl == official,
        },
        "U": {
            "denominator": int(u.get("denominator", -1)),
            "formal_valid_rows": int(u.get("formal_valid_rows", -1)),
        },
    }


def _validate_authority(o: dict, u: dict, pointer: dict) -> str:
    target = str(pointer.get("target_session") or "")
    if not target:
        raise CandidateAdapterError("POINTER_TARGET_SESSION_MISSING")
    osess, usess = o.get("target_session"), u.get("target_session")
    if osess != usess:
        raise CandidateAdapterError("AUTHORITY_CONFLICT_SESSION", f"O={osess} U={usess}")
    if osess != target:
        raise CandidateAdapterError("STALE_SESSION", f"receipt={osess} target={target}")
    if o.get("status") != pointer["sources"]["O"].get("expected_acceptance"):
        raise CandidateAdapterError("ACCEPTANCE_STATE_O")
    u_state = str(u.get("state") or "")
    if not u_state.startswith(str(pointer["sources"]["U"].get("expected_state_prefix") or "")):
        raise CandidateAdapterError("ACCEPTANCE_STATE_U")
    return target


def _snapshot_mismatches(snapshot: dict, o: dict, u: dict, target: str) -> list[dict]:
    out = []
    if snapshot.get("status") != "ACCEPTED_ENGINEERING":
        out.append({"code": "ORCHESTRATOR_ENGINEERING_NOT_ACCEPTED", "value": snapshot.get("status")})
    route = snapshot.get("current_route") or {}
    if route.get("target_session") not in (None, target):
        out.append({"code": "ORCHESTRATOR_TARGET_SESSION_MISMATCH", "value": route.get("target_session")})
    for track, receipt in (("O", o), ("U", u)):
        snap_session = (route.get(track) or {}).get("receipt_session")
        receipt_session = receipt.get("target_session")
        if snap_session != receipt_session:
            out.append({
                "code": f"PRODUCTION_SNAPSHOT_{track}_RECEIPT_SESSION_STALE",
                "snapshot": snap_session,
                "authority": receipt_session,
            })
    return out


def run_adapter(root: Path, pointer_path: Path) -> dict:
    root = root.resolve()
    pointer_path = _inside(root, pointer_path)
    pointer, pointer_bytes = _read_json(pointer_path, "GOVERNANCE_POINTER")
    if pointer.get("authority") != "NONE_READ_ONLY_SNAPSHOT":
        raise CandidateAdapterError("SECOND_AUTHORITY_LEDGER_FORBIDDEN")
    sources = pointer.get("sources") or {}
    required = {"O", "U", "orchestrator_module", "orchestrator_acceptance", "simulation_journal_readiness"}
    if not required.issubset(sources):
        raise CandidateAdapterError("POINTER_SOURCES_INCOMPLETE")

    o, oev = _verify_source(root, sources["O"], "O_RECEIPT")
    u, uev = _verify_source(root, sources["U"], "U_RECEIPT")
    snapshot, sev = _verify_source(root, sources["orchestrator_acceptance"], "ORCHESTRATOR_ACCEPTANCE")
    journal, jev = _verify_source(root, sources["simulation_journal_readiness"], "SIMULATION_JOURNAL_READINESS")
    mev = _verify_text_source(root, sources["orchestrator_module"], "ORCHESTRATOR_MODULE")

    target = _validate_authority(o, u, pointer)
    denominators = _validate_denominators(o, u, pointer)

    if journal.get("state") != "JOURNAL_INITIALIZED":
        raise CandidateAdapterError("SIMULATION_JOURNAL_NOT_READY", str(journal.get("state")))
    if int(journal.get("real_orders", -1)) != 0:
        raise CandidateAdapterError("SIMULATION_JOURNAL_REAL_ORDER_CONFLICT")

    adapter_tracks = {"O": _interpret_o(o, target), "U": _interpret_u(u, target)}

    scripts_dir = root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from dsa_production_orchestrator_v1 import classify_o, classify_u

    orchestrator_tracks = {"O": classify_o(o, target), "U": classify_u(u, target)}
    comparison = {}
    mismatch_inventory = _snapshot_mismatches(snapshot, o, u, target)
    for track in ("O", "U"):
        a = _projection(adapter_tracks[track])
        b = _projection(orchestrator_tracks[track])
        match = a == b
        comparison[track] = {"match": match, "adapter": a, "orchestrator": b}
        if not match:
            mismatch_inventory.append({"code": f"CLASSIFICATION_MISMATCH_{track}", "adapter": a, "orchestrator": b})

    if any(not comparison[t]["match"] for t in ("O", "U")):
        shadow_status = "FAIL_CLASSIFICATION_MISMATCH"
    elif mismatch_inventory:
        shadow_status = "PASS_WITH_MISMATCH_INVENTORY"
    else:
        shadow_status = "PASS_EXACT"

    result = {
        "schema_version": 1,
        "adapter_version": VERSION,
        "state": "PASS_READ_ONLY_ADAPTER",
        "parallel_shadow_status": shadow_status,
        "target_session": target,
        "governance_pointer": {
            "path": str(pointer_path.relative_to(root)),
            "sha256": _sha256(pointer_bytes),
            "foundation_source": pointer.get("foundation_source"),
        },
        "sources": {
            "O": oev,
            "U": uev,
            "orchestrator_module": mev,
            "orchestrator_acceptance": sev,
            "simulation_journal_readiness": jev,
        },
        "denominators": denominators,
        "tracks": {k: _projection(v) for k, v in adapter_tracks.items()},
        "comparison": comparison,
        "simulation_journal": {
            "state": journal.get("state"),
            "command_count": journal.get("command_count"),
            "journal_hash": journal.get("journal_hash"),
            "config_hash": journal.get("config_hash"),
            "real_orders": journal.get("real_orders"),
        },
        "mismatch_inventory": mismatch_inventory,
        "side_effects": {
            "authority_writes": 0,
            "model_logic_changes": 0,
            "strategy_parameter_changes": 0,
            "new_buy_created": 0,
            "simulation_writes": 0,
            "real_orders": 0,
        },
        "central_audit_ready": all(comparison[t]["match"] for t in ("O", "U")),
    }
    result["deterministic_receipt_sha256"] = _sha256(_canonical(result).encode())
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--governance", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    governance = args.governance if args.governance.is_absolute() else root / args.governance
    try:
        result = run_adapter(root, governance)
    except CandidateAdapterError as exc:
        print(_canonical({"adapter_version": VERSION, "state": "FAIL_CLOSED", "code": exc.code, "detail": exc.detail}))
        return 2
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        out = args.output if args.output.is_absolute() else root / args.output
        out = _inside(root, out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
