"""Typed deterministic canonical hashing for native DSA context objects.

This is an external acceptance-layer compatibility helper. It does not modify
frozen upstream data, prompts, model output, strategy rules or trade authority.
The native pipeline may carry ``datetime.date`` / ``datetime.datetime`` values
that are not JSON serializable.  Hashing must represent them deterministically
without silently colliding with an ordinary ISO-formatted string.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import math

VERSION = "O_NATIVE_CONTEXT_CANONICAL_v1"


def _json_default(value):
    if isinstance(value, datetime):
        return {"__dsa_type__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__dsa_type__": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NONFINITE_DECIMAL_NOT_CANONICAL")
        return {"__dsa_type__": "decimal", "value": str(value)}
    raise TypeError(f"UNSUPPORTED_CANONICAL_TYPE:{type(value).__name__}")


def canonical_hash(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def install_into_semantic_contract():
    """Patch only acceptance-layer canonical-hash globals for this process.

    Import this before the existing Gate-A probe. The frozen upstream checkout is
    untouched. The semantic module resolves its global ``canonical_hash`` at call
    time; post-output imports are updated too if already loaded.
    """
    import o_semantic_handoff_contract as semantic

    semantic.canonical_hash = canonical_hash
    try:
        import o_post_output_contract as post_output
    except ModuleNotFoundError:
        post_output = None
    if post_output is not None:
        post_output.canonical_hash = canonical_hash
    return {
        "version": VERSION,
        "semantic_contract_patched": semantic.canonical_hash is canonical_hash,
        "post_output_contract_patched": (
            None if post_output is None else post_output.canonical_hash is canonical_hash
        ),
        "frozen_upstream_mutated": False,
        "model_requests": 0,
        "runtime_activated": False,
    }
