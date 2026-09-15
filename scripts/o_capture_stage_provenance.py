"""Model-free provenance for the existing O observer's saved count fields.

A raw analyzer-return snapshot is not the pipeline's final annotated result.
This additive diagnostic does not change native fields, existing semantic gates,
news handoff policies, formal acceptance, or the observer itself.
"""
from __future__ import annotations
import ast
from copy import deepcopy
import hashlib
import json

VERSION = 'O_CAPTURE_STAGE_PROVENANCE_v1'
FROZEN_UPSTREAM = '089d9d26d68f8b839ea5a74a3784e4402925f8b7'
PINNED_SHA256 = {
    'analyzer': 'c2fb7c272ae5b9c12075f2f4e2f55016083857c109273e39b08e82e753e790db',
    'pipeline': '6c56bf1c3eeba956e55d6aef172b4519a9a2f8708b0d135d8a51ce256827da5b',
    'observer': '289f07f5f92f146a0303253531c2567991ffa5abaf6817b83d09f137e9b15153',
}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _functions(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]


def prove_capture_stage(analyzer: bytes, pipeline: bytes, observer: bytes) -> dict:
    """Verify exact public source bytes and AST ordering; execute no source code.

    This proves the saved field's provenance in these pinned sources. It does
    not prove a provider request, runtime branch execution or final search count.
    """
    sources = {'analyzer': analyzer, 'pipeline': pipeline, 'observer': observer}
    got = {key: _hash(raw) for key, raw in sources.items()}
    mismatch = sorted(key for key in sources if got[key] != PINNED_SHA256[key])
    if mismatch:
        raise ValueError('PINNED_SOURCE_HASH_MISMATCH:' + ','.join(mismatch))
    trees = {key: ast.parse(raw.decode('utf-8')) for key, raw in sources.items()}
    cls = next(n for n in trees['analyzer'].body if isinstance(n, ast.ClassDef) and n.name == 'AnalysisResult')
    fields = {n.target.id: n for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    assert ast.literal_eval(fields['news_result_count'].value) is None
    assert ast.literal_eval(fields['news_result_count_known'].value) is True
    wrapper = _functions(trees['observer'], 'analyze')
    assert len(wrapper) == 1
    wrapper = wrapper[0]
    calls = [n.lineno for n in ast.walk(wrapper) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'original_analyze']
    writes = [n.lineno for n in ast.walk(wrapper) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == 'write_text'
              and any(isinstance(v, ast.Constant) and v.value == 'original-result.json'
                      for v in ast.walk(n.func.value))]
    returns = [n.lineno for n in ast.walk(wrapper) if isinstance(n, ast.Return)
               and isinstance(n.value, ast.Name) and n.value.id == 'result']
    assert len(calls) == len(writes) == len(returns) == 1
    assert calls[0] < writes[0] < returns[0]
    functions = _functions(trees['pipeline'], 'analyze_stock')
    assert len(functions) == 1
    function = functions[0]
    native_calls = [n.lineno for n in ast.walk(function) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'analyze'
                    and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == 'analyzer']
    annotations = [n.lineno for n in ast.walk(function) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                           and t.value.id == 'result' and t.attr == 'news_result_count'
                           for t in n.targets)]
    assert len(native_calls) == len(annotations) == 1 and native_calls[0] < annotations[0]
    return {
        'version': VERSION, 'status': 'PASS_PINNED_SOURCE_ORDER',
        'frozen_upstream': FROZEN_UPSTREAM, 'source_sha256': got,
        'capture_stage': 'ANALYZER_RETURN_BEFORE_PIPELINE_ANNOTATION',
        'source_lines': {'native_count_default': fields['news_result_count'].lineno,
                         'native_known_default': fields['news_result_count_known'].lineno,
                         'observer_analyze_call': calls[0], 'observer_result_write': writes[0],
                         'observer_return': returns[0], 'pipeline_analyze_call': native_calls[0],
                         'pipeline_count_annotation': annotations[0]},
        'source_code_executed': False, 'provider_request_sent': False,
        'runtime_execution_independently_proven': False,
    }


def assess_saved_count_stage(result: dict, provenance: dict) -> dict:
    """Append a stage-aware diagnostic; never rewrite result or relax a guard."""
    if not isinstance(result, dict) or not isinstance(provenance, dict):
        raise ValueError('MAPPING_REQUIRED')
    before = deepcopy((result, provenance))
    verified = (provenance.get('version') == VERSION
                and provenance.get('status') == 'PASS_PINNED_SOURCE_ORDER'
                and provenance.get('source_sha256') == PINNED_SHA256
                and provenance.get('capture_stage') == 'ANALYZER_RETURN_BEFORE_PIPELINE_ANNOTATION')
    raw = {key: {'present': key in result, 'value': deepcopy(result.get(key))}
           for key in ('news_result_count_known', 'news_result_count', 'search_performed', 'news_evidence_present')}
    output = {
        'version': VERSION,
        'source_result_canonical_sha256': _hash(json.dumps(result, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')),
        'status': 'UNKNOWN_AT_CAPTURE_STAGE' if verified else 'CAPTURE_STAGE_UNPROVEN',
        'native_fields': raw,
        'final_pipeline_search_count_known': False,
        'final_pipeline_search_count': None,
        'meaning': 'Saved analyzer-return fields cannot establish the later pipeline annotation.'
                   if verified else 'No accepted pinned-source stage proof supplied.',
        'raw_known_null_not_automatically_a_model_error': True,
        'existing_semantic_findings_overridden': False,
        'source_result_mutated': False,
        'o_single_stock_formal_acceptance': False,
        'repeat_model_request_permitted': False,
        'runtime_activated': False,
        'new_model_requests': 0,
    }
    assert (result, provenance) == before
    return output
