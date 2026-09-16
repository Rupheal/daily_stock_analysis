"""Model-free proof that the real observer captures post-pipeline metadata.

This test extracts the nested ``pipeline_analyze`` wrapper from the production
observer source.  It never imports or calls a provider and does not grant any
formal O/U/runtime acceptance.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import sys

import pytest

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "scripts"))

from o_post_output_contract import (  # noqa: E402
    CAPTURE_VERSION,
    FINAL_STAGE,
    CONTRACT_VERSION as POST_OUTPUT_VERSION,
    PINNED_SHA256,
    build_final_capture,
    evaluate_post_output_contract,
)
from o_semantic_handoff_contract import (  # noqa: E402
    CONTRACT_VERSION as HANDOFF_VERSION,
    FROZEN_UPSTREAM,
    ContractError,
)

PROBE = R / "scripts" / "run_hk_original_model_probe.py"


class Result:
    def __init__(self, data):
        self.data = deepcopy(data)

    def to_dict(self):
        return deepcopy(self.data)


def _factory(tmp_path, *, return_different_object=False):
    source = PROBE.read_text(encoding="utf-8")
    main = next(
        n for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    pipeline_fn = next(
        n for n in main.body
        if isinstance(n, ast.FunctionDef) and n.name == "pipeline_analyze"
    )

    analyzer_value = {
        "pattern_analysis": "低开，开盘低于前收",
        "action": "watch",
        "news_result_count_known": True,
        "news_result_count": None,
        "current_price": None,
        "search_performed": False,
    }
    returned = Result(analyzer_value)
    observed = {
        "context": {
            "code": "HK01810",
            "date": "2026-01-05",
            "today": {"date": "2026-01-05", "open": "10.0"},
            "yesterday": {"close": "10.2"},
        },
        "news_context": None,
        "analysis_context_pack_summary": None,
        "capture_stage": "ANALYZER_ENTRY",
    }
    preflight = {"symbol": "HK01810", "target": "2026-01-05", "news_count": 0}
    source_proof = {
        "frozen_upstream": FROZEN_UPSTREAM,
        "pipeline_sha256": PINNED_SHA256["pipeline"],
        "observer_sha256": "a" * 64,
        "pipeline_module_under_checkout": True,
    }
    (tmp_path / "original-result.json").write_text(
        json.dumps(analyzer_value), encoding="utf-8"
    )

    def original_pipeline_analyze(instance, *a, **kw):
        # Simulate metadata that becomes available only after the analyzer return.
        returned.data["news_result_count"] = 0
        if return_different_object:
            return Result(returned.data)
        return returned

    init = ast.parse(
        """def factory():
    final_capture_receipt = None
    output_contract_receipt = None
    output_semantic_receipt = None
    analyzer_snapshot = None
    captured_prompt = None
    returned_result = RETURNED_RESULT
    observed_input = OBSERVED_INPUT
    news_handoff = None
"""
    ).body[0]
    init.body.append(pipeline_fn)
    init.body.extend(
        ast.parse(
            """def state():
    return {
        'final_capture_receipt': final_capture_receipt,
        'output_contract_receipt': output_contract_receipt,
        'output_semantic_receipt': output_semantic_receipt,
        'analyzer_snapshot': analyzer_snapshot,
    }
return pipeline_analyze, state
"""
        ).body
    )
    module = ast.Module(body=[init], type_ignores=[])
    ast.fix_missing_locations(module)
    env = {
        "RETURNED_RESULT": returned,
        "OBSERVED_INPUT": observed,
        "original_pipeline_analyze": original_pipeline_analyze,
        "root": tmp_path,
        "json": json,
        "ContractError": ContractError,
        "build_final_capture": build_final_capture,
        "evaluate_post_output_contract": evaluate_post_output_contract,
        "preflight": preflight,
        "capture_source_proof": source_proof,
        "CONTRACT_VERSION": HANDOFF_VERSION,
        "POST_OUTPUT_VERSION": POST_OUTPUT_VERSION,
        "args": SimpleNamespace(news_handoff_v1=False),
    }
    exec(compile(module, "actual_pipeline_analyze", "exec"), env)
    pipeline_analyze, state = env["factory"]()
    return pipeline_analyze, state, returned


def test_actual_observer_captures_final_pipeline_metadata(tmp_path):
    pipeline_analyze, state, returned = _factory(tmp_path)
    got = pipeline_analyze(object())
    assert got is returned

    capture = json.loads((tmp_path / "pipeline-final-capture.json").read_text())
    final_result = json.loads((tmp_path / "pipeline-final-result.json").read_text())
    contract = json.loads((tmp_path / "post-output-contract.json").read_text())

    assert capture["version"] == CAPTURE_VERSION
    assert capture["stage"] == FINAL_STAGE
    assert capture["hook"] == "StockAnalysisPipeline.analyze_stock:AFTER_NORMAL_RETURN"
    assert capture["analyzer_result_sha256"] != capture["final_result_sha256"]
    assert final_result["news_result_count"] == 0
    assert contract["capture_verified"] is True
    assert contract["deterministic_facts"]["news_result_count"]["final_search_state"] == "SEARCHED_ZERO"
    assert contract["promotion_gate"]["o_single_stock_formal_acceptance"] is False
    assert contract["runtime_activated"] is False
    assert state()["analyzer_snapshot"]["news_result_count"] is None


def test_actual_observer_rejects_unproven_pipeline_identity(tmp_path):
    pipeline_analyze, _, _ = _factory(tmp_path, return_different_object=True)
    with pytest.raises(ContractError, match="FINAL_PIPELINE_RESULT_NOT_PROVEN"):
        pipeline_analyze(object())
    assert not (tmp_path / "pipeline-final-capture.json").exists()
