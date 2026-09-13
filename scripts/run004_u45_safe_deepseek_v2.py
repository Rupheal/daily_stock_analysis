"""Run004 U45 safe runner v2.

Preserves v1 input, privacy, cost, denominator and ranking behavior. The only
semantic repair is output normalization: the four required fields must exist
and pass the same strict validators; any additional model-generated keys are
ignored in memory and are never persisted, printed or hashed into the result.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.run004_u45_safe_deepseek as base

base.SCHEMA_VERSION = "run004-u45-safe-v2"
REQUIRED_KEYS = {"score", "stance", "confidence", "reason_codes"}


def validate_model_result_required_subset(value):
    if not isinstance(value, dict) or not REQUIRED_KEYS.issubset(value):
        raise ValueError("invalid_model_schema_missing_required")
    projected = {key: value[key] for key in REQUIRED_KEYS}
    score = projected["score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("invalid_score")
    if projected["stance"] not in base.STANCES or projected["confidence"] not in base.CONFIDENCES:
        raise ValueError("invalid_model_enum")
    reasons = projected["reason_codes"]
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= 3 or len(set(reasons)) != len(reasons):
        raise ValueError("invalid_reason_codes")
    if any(reason not in base.REASON_CODES for reason in reasons):
        raise ValueError("unknown_reason_code")
    return {
        "score": score,
        "stance": projected["stance"],
        "confidence": projected["confidence"],
        "reason_codes": reasons,
    }


# parse_provider_response resolves this module-global function in base at call time.
base.validate_model_result = validate_model_result_required_subset


def main():
    return base.execute(base.parser().parse_args())


if __name__ == "__main__":
    main()
