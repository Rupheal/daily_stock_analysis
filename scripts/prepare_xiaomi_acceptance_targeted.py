"""Run the existing Xiaomi fresh preflight under the frozen O target-session contract.

This adapter does not alter the preflight's price/news/issuer gates. It only
replaces the legacy target-date resolver with O_NATIVE_TARGET_SESSION_RULE_v1
for the duration of the call, then verifies that the produced preflight target
matches the frozen rule. No model credentials are used here.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import prepare_xiaomi_acceptance as base
from o_target_session_contract import RULE_VERSION, resolve_target_session


def prepare_targeted(root=None, allow_partial_news=False, include_primary_evidence=False):
    evaluated_at = datetime.now(timezone.utc)
    resolved = resolve_target_session(evaluated_at)
    expected = resolved.target_session

    original_resolver = base.get_effective_trading_date

    def frozen_resolver(market, current_time=None):
        if str(market).lower() != "hk":
            raise ValueError("O_TARGET_SESSION_ADAPTER_HK_ONLY")
        if current_time is not None:
            return resolve_target_session(current_time).target_session
        return expected

    base.get_effective_trading_date = frozen_resolver
    try:
        audit = base.prepare(
            root=root,
            allow_partial_news=allow_partial_news,
            include_primary_evidence=include_primary_evidence,
        )
    finally:
        base.get_effective_trading_date = original_resolver

    actual = str(audit.get("target"))
    if actual != expected.isoformat():
        raise ValueError("PREFLIGHT_TARGET_SESSION_CONTRACT_MISMATCH")

    receipt = {
        "rule_version": RULE_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "target_session": expected.isoformat(),
        "preflight_target": actual,
        "target_match": True,
        "model_http_requests": 0,
    }
    root_path = Path(root) if root is not None else base.REPO_ROOT / "probe"
    (root_path / "target-session-receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False)
    )
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
