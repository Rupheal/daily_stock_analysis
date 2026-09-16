"""Versioned deterministic session-fact anchor for O Gate-A inputs.

This external evidence/input contract exposes facts already independently
validated but omitted/ambiguous in the frozen formatted prompt: previous close,
opening direction, target-session close, and explicit realtime availability.
It does not change frozen upstream strategy scoring or model parameters.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

VERSION = "O_SESSION_FACT_ANCHOR_v1"


class SessionFactError(ValueError):
    pass


def _num(value):
    if value is None or isinstance(value, bool):
        raise SessionFactError("SESSION_FACT_NUMBER_MISSING")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise SessionFactError("SESSION_FACT_NUMBER_INVALID") from None
    if not number.is_finite() or number <= 0:
        raise SessionFactError("SESSION_FACT_NUMBER_INVALID")
    return number


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _realtime_available(context):
    contract = context.get("execution_contract") or {}
    if "realtime_quote_available" in contract:
        if type(contract.get("realtime_quote_available")) is not bool:
            raise SessionFactError("REALTIME_AVAILABILITY_NOT_BOOLEAN")
        return contract["realtime_quote_available"]
    today = context.get("today") or {}
    source = str(today.get("data_source") or "")
    if source.startswith("realtime:") or today.get("is_partial_bar") is True or today.get("is_estimated") is True:
        return True
    chain = ((context.get("fundamental_context") or {}).get("source_chain") or [])
    rows = [row for row in chain if isinstance(row, dict) and row.get("provider") == "realtime_quote"]
    if rows:
        return any(row.get("result") not in ("not_supported", "missing", "unavailable", "fetch_failed") for row in rows)
    raise SessionFactError("REALTIME_AVAILABILITY_UNPROVEN")


def build_session_fact_anchor(context, *, target_session):
    if not isinstance(context, dict):
        raise SessionFactError("SESSION_CONTEXT_NOT_MAPPING")
    today, yesterday = context.get("today") or {}, context.get("yesterday") or {}
    if str(context.get("date")) != str(target_session) or str(today.get("date")) != str(target_session):
        raise SessionFactError("SESSION_FACT_TARGET_MISMATCH")
    op, prev_close, close = _num(today.get("open")), _num(yesterday.get("close")), _num(today.get("close"))
    direction = "UP" if op > prev_close else "DOWN" if op < prev_close else "FLAT"
    label = {"UP": "高开", "DOWN": "低开", "FLAT": "平开"}[direction]
    live = _realtime_available(context)
    facts = {
        "version": VERSION,
        "target_session": str(target_session),
        "open": str(op),
        "previous_close": str(prev_close),
        "opening_direction": direction,
        "opening_label_zh": label,
        "target_session_close": str(close),
        "realtime_quote_available": live,
        "rules": [
            "开盘方向只按本块 open 与 previous_close 比较；不得把日内冲高、最高价或相对更早价格写成高开/低开依据。",
            "若 realtime_quote_available=false，target_session_close 只能称目标交易日收盘价或最新完整日线收盘价，不得称现价、实时价或当前价。",
            "若 realtime_quote_available=false，最终 JSON 中任何语义为实时/现价的 current_price 字段应为 null；不得用 target_session_close 冒充实时价格。",
            "本事实块只校正事实口径，不改变原策略评分、买卖阈值或风险偏好。"
        ],
    }
    digest = sha256(_canonical(facts).encode("utf-8")).hexdigest()
    text = "DSA-SESSION-FACT-ANCHOR " + digest + "\n" + json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2)
    return {
        "version": VERSION,
        "facts": facts,
        "text": text,
        "sha256": sha256(text.encode("utf-8")).hexdigest(),
        "realtime_quote_available": live,
        "model_requests": 0,
        "frozen_upstream_mutated": False,
    }


def build_session_fact_anchor_from_preflight(preflight):
    if not isinstance(preflight, dict):
        raise SessionFactError("PREFLIGHT_NOT_MAPPING")
    target = str(preflight.get("target") or "")
    contract = preflight.get("execution_contract")
    if not target or not isinstance(contract, dict):
        raise SessionFactError("PREFLIGHT_EXECUTION_CONTRACT_MISSING")
    context = {
        "date": target,
        "today": preflight.get("today"),
        "yesterday": preflight.get("yesterday"),
        "execution_contract": contract,
    }
    return build_session_fact_anchor(context, target_session=target)


def prove_session_fact_anchor(prompt, anchor):
    if not isinstance(prompt, str) or not isinstance(anchor, dict):
        raise SessionFactError("SESSION_FACT_PROMPT_OR_ANCHOR_MISSING")
    text = anchor.get("text")
    if not isinstance(text, str) or not text or prompt.count(text) != 1:
        raise SessionFactError("SESSION_FACT_PROMPT_DROPPED_OR_DUPLICATED")
    if sha256(text.encode("utf-8")).hexdigest() != anchor.get("sha256"):
        raise SessionFactError("SESSION_FACT_ANCHOR_HASH_MISMATCH")
    return {
        "version": VERSION,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "anchor_sha256": anchor["sha256"],
        "consumed_exactly_once": True,
        "model_requests": 0,
    }
