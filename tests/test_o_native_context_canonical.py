from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from o_native_context_canonical import canonical_hash, install_into_semantic_contract
import o_semantic_handoff_contract as semantic


def preflight():
    return {
        "passed": True,
        "prices_passed": True,
        "symbol": "HK01810",
        "target": "2026-09-15",
        "prepared_at": "2026-09-16T04:07:00+00:00",
        "component_status": {"news": "passed_limited_coverage"},
        "news_count": 1,
        "allowed_news_urls": ["https://example.org/item1"],
        "company_news_evidence": [{
            "event_id": "synthetic-e1",
            "title": "synthetic news",
            "summary": "model-free fixture only",
            "source": "fixture",
            "published_at": "2026-09-15T08:00:00+00:00",
            "source_urls": ["https://example.org/item1"],
            "source_records": [{"source": "fixture", "url": "https://example.org/item1"}],
            "evidence_kind": "summary",
        }],
    }


def native_context():
    return {
        "code": "HK01810",
        "date": date(2026, 9, 15),
        "news_window_days": 3,
        "today": {"date": date(2026, 9, 15), "open": 27.1200008392334},
        "yesterday": {"date": date(2026, 9, 14), "close": 27.15999984741211},
        "generated_at": datetime(2026, 9, 16, 4, 14, 19, tzinfo=timezone.utc),
    }


def test_native_date_context_is_canonical_and_repeatable():
    ctx = native_context()
    before = deepcopy(ctx)
    assert canonical_hash(ctx) == canonical_hash(ctx)
    assert ctx == before


def test_typed_date_does_not_collide_with_plain_iso_string():
    assert canonical_hash({"d": date(2026, 9, 15)}) != canonical_hash({"d": "2026-09-15"})


def test_typed_datetime_does_not_collide_with_plain_iso_string():
    dt = datetime(2026, 9, 16, 4, 14, 19, tzinfo=timezone.utc)
    assert canonical_hash({"d": dt}) != canonical_hash({"d": dt.isoformat()})


def test_decimal_is_typed_and_nonfinite_fails_closed():
    assert canonical_hash({"x": Decimal("27.12")}) != canonical_hash({"x": "27.12"})
    with pytest.raises(ValueError, match="NONFINITE_DECIMAL"):
        canonical_hash({"x": Decimal("NaN")})


def test_unknown_object_fails_closed():
    with pytest.raises(TypeError, match="UNSUPPORTED_CANONICAL_TYPE"):
        canonical_hash({"x": object()})


def test_nan_float_remains_rejected():
    with pytest.raises(ValueError):
        canonical_hash({"x": float("nan")})


def test_install_patches_semantic_and_post_output_without_frozen_mutation():
    receipt = install_into_semantic_contract()
    import o_post_output_contract as post_output
    assert receipt["semantic_contract_patched"] is True
    assert receipt["post_output_contract_patched"] is True
    assert semantic.canonical_hash is canonical_hash
    assert post_output.canonical_hash is canonical_hash
    assert receipt["frozen_upstream_mutated"] is False
    assert receipt["model_requests"] == 0


def test_real_shape_news_handoff_no_longer_crashes_on_date_objects():
    install_into_semantic_contract()
    p = preflight()
    ctx = native_context()
    bundle = semantic.build_news_handoff(
        p,
        ctx,
        expected_preflight_hash=canonical_hash(p),
        decision_at="2026-09-16T04:14:19+00:00",
    )
    assert bundle["native_context_hash"] == canonical_hash(ctx)
    assert bundle["symbol"] == "HK01810"
    assert bundle["target_session"] == "2026-09-15"
    assert bundle["admitted_evidence_count"] == 1
    assert bundle["model_http_requests"] == 0


def test_context_change_after_handoff_is_detected_with_date_objects():
    install_into_semantic_contract()
    p = preflight()
    ctx = native_context()
    bundle = semantic.build_news_handoff(
        p, ctx, expected_preflight_hash=canonical_hash(p),
        decision_at="2026-09-16T04:14:19+00:00",
    )
    changed = deepcopy(ctx)
    changed["today"]["open"] = 27.13
    assert canonical_hash(changed) != bundle["native_context_hash"]


def test_post_output_final_capture_accepts_date_objects_for_hashing_only():
    install_into_semantic_contract()
    from o_post_output_contract import build_final_capture
    p = preflight()
    original_input = {"context": native_context(), "news_context": "fixture"}
    analyzer = {"action": "watch", "news_result_count_known": True, "news_result_count": None}
    final = deepcopy(analyzer)
    source = {
        "frozen_upstream": semantic.FROZEN_UPSTREAM,
        "pipeline_sha256": "0" * 64,
        "observer_sha256": "1" * 64,
        "pipeline_module_under_checkout": True,
    }
    receipt = build_final_capture(
        p, original_input, analyzer, final,
        source_proof=source, input_version=semantic.CONTRACT_VERSION,
    )
    assert receipt["input_sha256"] == canonical_hash(original_input)
    assert receipt["pipeline_returned"] is True
