"""Run057 deterministic O608 native-execution rollout planner.

No model/provider/network calls are made here. The planner reconciles the frozen
660-name O denominator, 52 retained historical isolations, and already-spent
O original-native slots before any future batch can be armed.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import glob
import hashlib
import json
from pathlib import Path
import re

RUN_ID = "TRI-DSA-RESUME-20260917-057"
CODE_RE = re.compile(r"^(?:HK|hk)?(\d{5})$")
SPEND_KEYS = {
    "model_http_requests",
    "model_http_requests_confirmed",
    "native_model_http_requests",
    "http_confirmed",
}


def read_json(path: Path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def normalize_code(value):
    if value is None:
        return None
    m = CODE_RE.fullmatch(str(value).strip())
    return m.group(1) if m else None


def deep_spend(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in SPEND_KEYS:
                try:
                    if int(value) > 0:
                        return True
                except (TypeError, ValueError):
                    pass
            if key == "request_status" and value == "response_received":
                return True
            if deep_spend(value):
                return True
    elif isinstance(obj, list):
        return any(deep_spend(x) for x in obj)
    return False


def code_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return None
    for key in ("code", "target", "symbol"):
        code = normalize_code(mapping.get(key))
        if code:
            return code
    return None


def collect_spent_codes(obj, source, inherited_code=None, out=None):
    """Collect code-bound spent/claimed nodes from an O-scoped receipt."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        local_code = code_from_mapping(obj) or inherited_code
        claimed = obj.get("claim_persisted") is True
        direct_spend = False
        for key in SPEND_KEYS:
            value = obj.get(key)
            try:
                direct_spend = direct_spend or int(value) > 0
            except (TypeError, ValueError):
                pass
        direct_spend = direct_spend or obj.get("request_status") == "response_received"
        # Top-level O receipts such as O_SINGLE_NATIVE_ACCEPTANCE bind target
        # outside the nested technical_execution object. deep_spend handles it.
        if local_code and (claimed or direct_spend or (inherited_code is None and deep_spend(obj))):
            reasons = out.setdefault(local_code, set())
            if claimed:
                reasons.add(f"{source}:durable_claim")
            if direct_spend or deep_spend(obj):
                reasons.add(f"{source}:provider_spend_or_response")
        for value in obj.values():
            collect_spent_codes(value, source, local_code, out)
    elif isinstance(obj, list):
        for value in obj:
            collect_spent_codes(value, source, inherited_code, out)
    return out


def partition(items, width):
    if width <= 0:
        raise ValueError("BAD_PARTITION_WIDTH")
    return [items[i:i + width] for i in range(0, len(items), width)]


def build(root: Path, scope: dict):
    inputs = scope["inputs"]
    paths = {k: root / v for k, v in inputs.items() if isinstance(v, str) and k != "o_receipt_glob"}
    universe, universe_sha = read_json(paths["official_universe"])
    ready_receipt, ready_sha = read_json(paths["input_readiness"])
    o52, o52_sha = read_json(paths["o52_current_audit"])
    run050, run050_sha = read_json(paths["structural_adjudication"])
    run051, run051_sha = read_json(paths["third_source_adjudication"])
    run052, run052_sha = read_json(paths["geometry_adjudication"])

    members = universe.get("members") or []
    universe_codes = [normalize_code(x.get("code")) for x in members]
    if len(universe_codes) != 660 or None in universe_codes or len(set(universe_codes)) != 660:
        raise ValueError("O_UNIVERSE_660_UNIQUENESS_FAIL")
    if universe.get("member_count") != 660 or universe.get("full_union_verified") is not True:
        raise ValueError("O_UNIVERSE_CONTRACT_FAIL")

    isolated_rows = o52.get("rows") or []
    isolated_codes = sorted({
        normalize_code(r.get("code"))
        for r in isolated_rows
        if r.get("prior_status") == "ISOLATED"
    })
    if None in isolated_codes or len(isolated_codes) != 52:
        raise ValueError("O52_ISOLATION_SET_FAIL")
    if not set(isolated_codes) <= set(universe_codes):
        raise ValueError("O52_NOT_SUBSET_OF_UNIVERSE")

    dc = scope["denominator_contract"]
    if dc != {
        "O_universe": 660,
        "deterministic_ready": 608,
        "retained_isolated": 52,
        "release_from_isolation_in_run057": 0,
        "drop_from_denominator": 0,
    }:
        raise ValueError("RUN057_DENOMINATOR_SCOPE_CHANGED")
    if ready_receipt.get("O_denominator") != 660 or ready_receipt.get("input_ready") != 608 or ready_receipt.get("isolated") != 52:
        raise ValueError("RUN045_READY_COUNTS_MISMATCH")

    if run050.get("result", {}).get("released_from_isolation") != 0 or run050.get("result", {}).get("retained_structural_isolations") != 4:
        raise ValueError("RUN050_RELEASE_CONFLICT")
    if run051.get("result", {}).get("released") != 0 or run051.get("result", {}).get("retained") != 32:
        raise ValueError("RUN051_RELEASE_CONFLICT")
    if run052.get("result", {}).get("released") != 0 or run052.get("result", {}).get("retained") != 16:
        raise ValueError("RUN052_RELEASE_CONFLICT")

    ready_codes = sorted(set(universe_codes) - set(isolated_codes))
    if len(ready_codes) != 608:
        raise ValueError("READY_SET_NOT_608")

    # O-prefixed receipts are track-scoped by filename. Explicit receipts cover
    # later mixed-name files that contain O original-native claims.
    receipt_paths = set()
    if scope["no_repeat_contract"].get("scan_o_prefixed_receipts"):
        pattern = str(root / inputs["o_receipt_glob"])
        receipt_paths.update(Path(p) for p in glob.glob(pattern))
    if scope["no_repeat_contract"].get("scan_explicit_receipts"):
        receipt_paths.update(root / p for p in inputs["explicit_prior_call_receipts"])

    spent = {}
    receipt_hashes = {}
    for path in sorted(receipt_paths):
        if not path.exists():
            raise ValueError(f"PRIOR_O_RECEIPT_MISSING:{path.relative_to(root)}")
        doc, sha = read_json(path)
        rel = str(path.relative_to(root))
        receipt_hashes[rel] = sha
        found = collect_spent_codes(doc, rel)
        for code, reasons in found.items():
            spent.setdefault(code, set()).update(reasons)

    spent_codes = sorted(spent)
    known_minimum = set(scope["no_repeat_contract"]["known_minimum_spent_codes"])
    if not known_minimum <= set(spent_codes):
        missing = sorted(known_minimum - set(spent_codes))
        raise ValueError("KNOWN_SPENT_CODE_NOT_RECOVERED:" + ",".join(missing))

    no_repeat_ready = sorted(set(spent_codes) & set(ready_codes))
    spent_outside_ready = sorted(set(spent_codes) - set(ready_codes))
    never_called = sorted(set(ready_codes) - set(no_repeat_ready))
    if set(never_called) & set(no_repeat_ready):
        raise AssertionError("NO_REPEAT_OVERLAP")
    if len(never_called) + len(no_repeat_ready) != 608:
        raise AssertionError("READY_PARTITION_FAIL")

    ec = scope["execution_contract"]
    micro_width = int(ec["current_proven_microbatch_width"])
    tranche_members = int(ec["planning_tranche_members"])
    if micro_width != 2 or tranche_members < micro_width or tranche_members % micro_width:
        raise ValueError("UNPROVEN_BATCH_GEOMETRY")
    cap = Decimal(ec["hard_cap_cny_per_never_called_member"])
    if cap != Decimal("0.10"):
        raise ValueError("UNAPPROVED_PER_MEMBER_CAP")

    micro_chunks = partition(never_called, micro_width)
    micro_batches = [
        {
            "micro_batch_id": f"O57-MB-{i:03d}",
            "codes": codes,
            "member_count": len(codes),
            "hard_cap_cny": str(cap * len(codes)),
            "send_authorized_by_run057": False,
        }
        for i, codes in enumerate(micro_chunks, 1)
    ]
    tranche_chunks = partition(micro_batches, tranche_members // micro_width)
    tranches = []
    for i, group in enumerate(tranche_chunks, 1):
        codes = [c for batch in group for c in batch["codes"]]
        tranches.append({
            "tranche_id": f"O57-TR-{i:02d}",
            "micro_batch_ids": [b["micro_batch_id"] for b in group],
            "codes": codes,
            "member_count": len(codes),
            "hard_cap_cny": str(cap * len(codes)),
            "send_authorized_by_run057": False,
        })

    flattened = [c for b in micro_batches for c in b["codes"]]
    if flattened != never_called or len(flattened) != len(set(flattened)):
        raise AssertionError("MICROBATCH_COVERAGE_FAIL")
    tranche_flat = [c for t in tranches for c in t["codes"]]
    if tranche_flat != never_called:
        raise AssertionError("TRANCHE_COVERAGE_FAIL")

    identity = {normalize_code(x["code"]): {
        "official_name": x.get("official_name"),
        "english_name": x.get("english_name"),
        "isin": x.get("isin"),
        "channels": x.get("channels"),
        "board_lot": x.get("board_lot"),
        "currency": x.get("currency"),
    } for x in members}

    input_hashes = {
        inputs["official_universe"]: universe_sha,
        inputs["input_readiness"]: ready_sha,
        inputs["o52_current_audit"]: o52_sha,
        inputs["structural_adjudication"]: run050_sha,
        inputs["third_source_adjudication"]: run051_sha,
        inputs["geometry_adjudication"]: run052_sha,
    }

    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "target_session": scope["target_session"],
        "state": "PASS_ZERO_MODEL_O_NATIVE_ROLLOUT_PLAN",
        "authoritative_parent_head": scope["authoritative_parent_head"],
        "denominator": {
            "O_universe": 660,
            "deterministic_ready": len(ready_codes),
            "retained_isolated": len(isolated_codes),
            "released_from_isolation": 0,
            "removed_from_denominator": 0,
        },
        "isolation": {
            "codes": isolated_codes,
            "classification_counts": {
                "structural": 4,
                "third_source_conflict": 32,
                "invalid_bar_geometry": 16,
            },
            "reopen_rule": "NEW_APPEND_ONLY_EVIDENCE_ONLY",
        },
        "no_repeat": {
            "spent_codes_all_o_receipts": spent_codes,
            "spent_codes_within_ready": no_repeat_ready,
            "spent_codes_outside_ready": spent_outside_ready,
            "count_within_ready": len(no_repeat_ready),
            "evidence": {code: sorted(spent[code]) for code in spent_codes},
            "known_minimum_recovered": sorted(known_minimum),
            "repeat_permission_from_run057": False,
        },
        "rollout": {
            "native_model_configuration": ec["native_model_configuration"],
            "ready_codes": ready_codes,
            "never_called_codes": never_called,
            "never_called_count": len(never_called),
            "micro_batch_width": micro_width,
            "micro_batch_count": len(micro_batches),
            "planning_tranche_members": tranche_members,
            "tranche_count": len(tranches),
            "micro_batches": micro_batches,
            "tranches": tranches,
            "conservative_provider_hard_cap_cny": str(cap * len(never_called)),
            "hard_cap_basis": "0.10 CNY per never-called member maximum; each actual send still requires a fresh lower/equal pre-send envelope and balance/Drive gates.",
            "send_authorized_by_run057": False,
        },
        "identity": {
            "ready": {code: identity[code] for code in ready_codes},
            "isolated": {code: identity[code] for code in isolated_codes},
        },
        "input_sha256": input_hashes,
        "prior_o_receipt_sha256": receipt_hashes,
        "resource_accounting": {
            "model_http_requests": 0,
            "paid_data_calls": 0,
            "DeepSeek_API_cost_cny": 0,
            "actual_charge_cny": 0,
            "real_orders": 0,
            "simulation_writes": 0,
            "schedule_changes": 0,
            "automatic_recharge": False,
        },
        "next": "Run058 may implement a resumable serialized O rollout controller over this immutable plan. It must reconcile durable claims before every send, execute only never-called deterministic-PASS members, stop after ambiguous/private failures, and must not release the 52 historical isolates.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--scope", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    scope, _ = read_json(args.scope)
    if scope.get("run_id") != RUN_ID or scope.get("resource_plan", {}).get("model_http_requests") != 0:
        raise ValueError("RUN057_SCOPE_MISMATCH")
    result = build(args.root, scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "ready": result["denominator"]["deterministic_ready"],
        "isolated": result["denominator"]["retained_isolated"],
        "no_repeat_ready": result["no_repeat"]["count_within_ready"],
        "never_called": result["rollout"]["never_called_count"],
        "micro_batches": result["rollout"]["micro_batch_count"],
        "tranches": result["rollout"]["tranche_count"],
        "hard_cap_cny": result["rollout"]["conservative_provider_hard_cap_cny"],
        "model_http_requests": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
