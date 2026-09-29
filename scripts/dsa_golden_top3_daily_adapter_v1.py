#!/usr/bin/env python3
"""Golden DSA HK Top3 Daily Adapter v1.

Read-only projection seam from the repository's existing formal O/U receipt
resolver into one stable daily Top3 contract. The adapter does not rank stocks,
create BUY decisions, issue simulation commands, or mint Authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from .dsa_formal_receipt_resolver_v1 import resolve
    from .dsa_production_orchestrator_v1 import classify_o, classify_u
else:
    from dsa_formal_receipt_resolver_v1 import resolve
    from dsa_production_orchestrator_v1 import classify_o, classify_u

VERSION = "GOLDEN_DSA_HK_TOP3_DAILY_ADAPTER_v1"
AUTHORITY = "NONE_PROJECTION_ONLY"


class GoldenAdapterError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise GoldenAdapterError("PATH_ESCAPE", str(path)) from exc
    return resolved


def _source_meta(root: Path, path_value: str, receipt: dict, track: str) -> dict:
    path = _inside(root, Path(path_value))
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(root.resolve())),
        "sha256": _sha256(raw),
        "target_session": receipt.get("target_session"),
        "formal_state": receipt.get("status") if track == "O" else receipt.get("state"),
    }


def _project_top3(track: str, classified: dict) -> list[dict]:
    rows = classified.get("candidates") or []
    if len(rows) > 3:
        raise GoldenAdapterError(f"TOP3_TOO_LONG_{track}", str(len(rows)))

    out = []
    seen = set()
    for row in rows:
        code = str(row.get("code") or "")
        if not code:
            raise GoldenAdapterError(f"TOP3_CODE_MISSING_{track}")
        if code in seen:
            raise GoldenAdapterError(f"DUPLICATE_TOP3_CODE_{track}", code)
        seen.add(code)

        rank = row.get("rank")
        if type(rank) is not int or rank not in (1, 2, 3):
            raise GoldenAdapterError(f"TOP3_RANK_INVALID_{track}", f"{code}:{rank}")

        out.append(
            {
                "code": code,
                "name": row.get("name"),
                "rank": rank,
                "score": row.get("score"),
                "industry": row.get("industry"),
                "action": row.get("action"),
                "buyable_verified": bool(row.get("buyable_verified")),
            }
        )
    return out


def _project_track(track: str, classified: dict) -> dict:
    state = classified.get("state")
    if state in {"BLOCKED", "STALE"}:
        blockers = ",".join(classified.get("blockers") or [])
        raise GoldenAdapterError(f"CLASSIFICATION_NOT_CONSUMABLE_{track}", f"{state}:{blockers}")
    if state not in {"WAIT", "QUALIFIED_BUY"}:
        raise GoldenAdapterError(f"CLASSIFICATION_STATE_UNKNOWN_{track}", str(state))

    top3 = _project_top3(track, classified)
    qualified_buy = int(classified.get("qualified_buy", 0) or 0)
    projected_buy = sum(1 for row in top3 if row["action"] == "BUY")
    if qualified_buy != projected_buy:
        raise GoldenAdapterError(
            f"QUALIFIED_BUY_PROJECTION_MISMATCH_{track}",
            f"classified={qualified_buy}:projected={projected_buy}",
        )

    return {
        "state": state,
        "qualified_buy": qualified_buy,
        "top3": top3,
    }


def build_golden_daily(root: Path, target_session: str) -> dict:
    """Build one deterministic, projection-only O/U daily Top3 envelope."""
    root = root.resolve()
    resolved = resolve(root, target_session)
    if resolved.get("state") != "READY":
        raise GoldenAdapterError("FORMAL_RECEIPTS_NOT_READY", str(resolved.get("state")))

    o_path = resolved["O"].get("path")
    u_path = resolved["U"].get("path")
    o_receipt = resolved["O"].get("receipt")
    u_receipt = resolved["U"].get("receipt")
    if not o_path or not u_path or not isinstance(o_receipt, dict) or not isinstance(u_receipt, dict):
        raise GoldenAdapterError("FORMAL_RECEIPT_RESOLUTION_INCOMPLETE")

    o_classified = classify_o(o_receipt, target_session)
    u_classified = classify_u(u_receipt, target_session)
    tracks = {
        "O": _project_track("O", o_classified),
        "U": _project_track("U", u_classified),
    }
    qualified_buy_total = tracks["O"]["qualified_buy"] + tracks["U"]["qualified_buy"]

    result = {
        "schema_version": 1,
        "adapter_version": VERSION,
        "market": "XHKG",
        "target_session": target_session,
        "state": "READY",
        "decision_state": "QUALIFIED_BUY_PRESENT" if qualified_buy_total else "WAIT_NO_BUY",
        "authority": AUTHORITY,
        "tracks": tracks,
        "qualified_buy_total": qualified_buy_total,
        "sources": {
            "O": _source_meta(root, o_path, o_receipt, "O"),
            "U": _source_meta(root, u_path, u_receipt, "U"),
        },
        "side_effects": {
            "model_calls": 0,
            "authority_writes": 0,
            "simulation_writes": 0,
            "broker_orders": 0,
            "real_orders": 0,
        },
        "boundaries": {
            "changes_model_or_ranking_logic": False,
            "promotes_top10_to_top3": False,
            "creates_buy_decisions": False,
            "creates_entry_or_signal_commands": False,
            "requires_production_orchestrator_for_execution": True,
        },
    }
    result["deterministic_receipt_sha256"] = _sha256(_canonical(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--target-session", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        result = build_golden_daily(root, args.target_session)
    except (GoldenAdapterError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, GoldenAdapterError) else type(exc).__name__
        detail = exc.detail if isinstance(exc, GoldenAdapterError) else str(exc)
        print(
            json.dumps(
                {
                    "adapter_version": VERSION,
                    "state": "FAIL_CLOSED",
                    "code": code,
                    "detail": detail,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        out = args.out if args.out.is_absolute() else root / args.out
        out = _inside(root, out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
