"""Versioned deterministic coverage-limitation adapter for O native news handoff.

This adapter does not add news, claim a search occurred, alter prices, scoring, or
strategy fields. It only appends an explicit evidence limitation when the
preflight/news handoff is not complete enough to support absence-of-adverse-news
claims. The frozen upstream prompt template remains unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

VERSION = "O_NEWS_COVERAGE_LIMITATION_v1"

LIMITATION_TEXT = (
    "DSA-NEWS-COVERAGE-LIMITATION "
    + VERSION
    + "\n"
    + "新闻证据覆盖不完整，且当前证据包不能证明不存在未收录、未报道或未复核的负面事件。"
    + "不得把“未提供新闻”“未检出新闻”或“有限来源未命中”解释为没有利空。"
    + "禁止输出“未见利空”“未发现负面”“没有利空”“暂无利空”或“近N日无利空”等缺乏完整复核支撑的结论。"
    + "如需描述新闻风险，只能明确表述：新闻复核不完整，无法排除未报道风险。"
)


class CoverageLimitationError(ValueError):
    pass


def apply_coverage_limitation(handoff: dict, preflight: dict) -> dict:
    if not isinstance(handoff, dict) or not isinstance(preflight, dict):
        raise CoverageLimitationError("COVERAGE_ADAPTER_INPUT_INVALID")
    original = handoff.get("news_context")
    if not isinstance(original, str) or not original.strip():
        raise CoverageLimitationError("NEWS_CONTEXT_REQUIRED")
    expected = handoff.get("news_context_sha256")
    if expected != sha256(original.encode()).hexdigest():
        raise CoverageLimitationError("NEWS_CONTEXT_HASH_MISMATCH")

    complete = bool(preflight.get("risk_review_complete")) and bool(handoff.get("full_coverage"))
    out = deepcopy(handoff)
    if complete:
        out["coverage_limitation_adapter"] = {
            "version": VERSION,
            "applied": False,
            "reason": "COMPLETE_REVIEW_ALREADY_PROVEN",
            "model_requests": 0,
            "news_items_added": 0,
            "native_strategy_fields_changed": False,
        }
        return out

    if LIMITATION_TEXT in original:
        raise CoverageLimitationError("COVERAGE_LIMITATION_DUPLICATED")
    out["news_context"] = (original.rstrip() + "\n\n" + LIMITATION_TEXT).strip()
    out["news_context_sha256"] = sha256(out["news_context"].encode()).hexdigest()
    out["coverage_limitation_adapter"] = {
        "version": VERSION,
        "applied": True,
        "reason": "INCOMPLETE_NEWS_REVIEW_CANNOT_SUPPORT_ADVERSE_NEWS_ABSENCE_CLAIMS",
        "model_requests": 0,
        "news_items_added": 0,
        "search_performed_changed": False,
        "full_coverage_changed": False,
        "native_strategy_fields_changed": False,
        "limitation_sha256": sha256(LIMITATION_TEXT.encode()).hexdigest(),
    }
    return out
