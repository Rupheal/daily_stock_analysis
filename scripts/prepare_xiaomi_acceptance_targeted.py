"""Run the Xiaomi fresh preflight under the frozen O target-session contract.

The adapter keeps price/news/issuer acceptance thresholds unchanged, freezes the
completed XHKG target, applies bounded Yahoo retrieval mechanics, and records the
Gate-A runtime quote policy explicitly in the resulting preflight.  That explicit
policy lets downstream evidence handoff distinguish target-session close from a
true realtime quote without relying on hidden environment state.
No model credentials are used here.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import prepare_xiaomi_acceptance as base
from o_target_session_contract import RULE_VERSION, resolve_target_session


def _write_receipt(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))


def _bounded_history_kwargs(expected, kwargs):
    out = dict(kwargs)
    if out.get("period") == "6mo" and not out.get("start") and not out.get("end"):
        out.pop("period", None)
        out["start"] = (expected - timedelta(days=200)).isoformat()
        out["end"] = (expected + timedelta(days=1)).isoformat()
        out["repair"] = True
    return out


class _BoundedTicker:
    def __init__(self, inner, expected):
        self._inner = inner
        self._expected = expected

    def history(self, *args, **kwargs):
        return self._inner.history(*args, **_bounded_history_kwargs(self._expected, kwargs))


class _BoundedYFinance:
    def __init__(self, original, expected):
        self._original = original
        self._expected = expected

    def Ticker(self, symbol):
        return _BoundedTicker(self._original.Ticker(symbol), self._expected)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"INVALID_BOOLEAN_ENV:{name}")


def prepare_targeted(root=None, allow_partial_news=False, include_primary_evidence=False):
    evaluated_at = datetime.now(timezone.utc)
    resolved = resolve_target_session(evaluated_at)
    expected = resolved.target_session
    root_path = Path(root) if root is not None else base.REPO_ROOT / "probe"
    receipt_path = root_path / "target-session-receipt.json"

    realtime_quote_available = _env_bool("ENABLE_REALTIME_QUOTE", False)
    execution_contract = {
        "version": "O_GATE_A_EXECUTION_CONTRACT_v2",
        "target_session": expected.isoformat(),
        "realtime_quote_available": realtime_quote_available,
        "realtime_policy_source": "ENABLE_REALTIME_QUOTE",
        "session_fact_anchor_required": True,
        "meaning": "When realtime_quote_available is false, target-session close is not a live/current quote."
    }

    receipt = {
        "rule_version": RULE_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "target_session": expected.isoformat(),
        "yahoo_retrieval_boundary": (expected + timedelta(days=1)).isoformat(),
        "yahoo_end_semantics": "exclusive",
        "yahoo_repair_enabled": True,
        "execution_contract": execution_contract,
        "preflight_target": None,
        "target_match": None,
        "status": "TARGET_RESOLVED_BEFORE_PREFLIGHT",
        "model_http_requests": 0,
    }
    _write_receipt(receipt_path, receipt)

    original_resolver = base.get_effective_trading_date
    original_yf = base.yf

    def frozen_resolver(market, current_time=None):
        if str(market).lower() != "hk":
            raise ValueError("O_TARGET_SESSION_ADAPTER_HK_ONLY")
        if current_time is not None:
            return resolve_target_session(current_time).target_session
        return expected

    base.get_effective_trading_date = frozen_resolver
    base.yf = _BoundedYFinance(original_yf, expected)
    try:
        audit = base.prepare(
            root=root,
            allow_partial_news=allow_partial_news,
            include_primary_evidence=include_primary_evidence,
        )
    except Exception as exc:
        receipt.update(
            status="PREFLIGHT_FAILED_AFTER_TARGET_RESOLUTION",
            failure_type=type(exc).__name__,
            failure_message=str(exc),
        )
        _write_receipt(receipt_path, receipt)
        raise
    finally:
        base.get_effective_trading_date = original_resolver
        base.yf = original_yf

    actual = str(audit.get("target"))
    if actual != expected.isoformat():
        receipt.update(
            preflight_target=actual,
            target_match=False,
            status="PREFLIGHT_TARGET_SESSION_CONTRACT_MISMATCH",
        )
        _write_receipt(receipt_path, receipt)
        raise ValueError("PREFLIGHT_TARGET_SESSION_CONTRACT_MISMATCH")

    # This is an additive execution-policy receipt, not a market-data override.
    # It is written into the preflight before downstream hashing/claim creation.
    audit["execution_contract"] = execution_contract
    _write_receipt(root_path / "preflight.json", audit)

    receipt.update(
        preflight_target=actual,
        target_match=True,
        status="PREFLIGHT_COMPLETED_TARGET_MATCH",
    )
    _write_receipt(receipt_path, receipt)
    return audit, receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-primary-evidence", action="store_true")
    parser.add_argument("--allow-partial-news", action="store_true")
    args = parser.parse_args()
    audit, receipt = prepare_targeted(
        allow_partial_news=args.allow_partial_news,
        include_primary_evidence=args.with_primary_evidence,
    )
    print("TARGET_SESSION_RECEIPT", json.dumps(receipt, ensure_ascii=False))
