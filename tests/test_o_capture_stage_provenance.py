"""Synthetic metadata and exact pinned public-source AST tests; zero model calls."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from o_capture_stage_provenance import (
    PINNED_SHA256, VERSION, assess_saved_count_stage, prove_capture_stage,
)


@pytest.fixture(scope='module')
def source_bytes():
    paths = {
        'analyzer': Path(os.environ['DSA_FROZEN_ANALYZER_SOURCE']),
        'pipeline': Path(os.environ['DSA_FROZEN_PIPELINE_SOURCE']),
        'observer': Path(os.environ['DSA_OBSERVER_SOURCE']),
    }
    return {key: path.read_bytes() for key, path in paths.items()}


@pytest.fixture(scope='module')
def proof(source_bytes):
    return prove_capture_stage(**source_bytes)


def test_exact_source_capture_order(proof):
    assert proof['source_lines'] == {
        'native_count_default': 1730, 'native_known_default': 1733,
        'observer_analyze_call': 99, 'observer_result_write': 101,
        'observer_return': 103, 'pipeline_analyze_call': 843,
        'pipeline_count_annotation': 854,
    }
    assert proof['source_sha256'] == PINNED_SHA256
    assert proof['status'] == 'PASS_PINNED_SOURCE_ORDER'
    assert not proof['source_code_executed']
    assert not proof['runtime_execution_independently_proven']


@pytest.mark.parametrize('source', ['analyzer', 'pipeline', 'observer'])
def test_changed_source_is_not_silently_accepted(source_bytes, source):
    altered = dict(source_bytes); altered[source] += b'\n'
    with pytest.raises(ValueError, match='PINNED_SOURCE_HASH_MISMATCH'):
        prove_capture_stage(**altered)


@pytest.mark.parametrize('count', [None, 0, 4, True, -1, '4', 1.2])
def test_early_snapshot_never_proves_final_count(proof, count):
    result = {'news_result_count_known': True, 'news_result_count': count}
    out = assess_saved_count_stage(result, proof)
    assert out['status'] == 'UNKNOWN_AT_CAPTURE_STAGE'
    assert out['native_fields']['news_result_count']['value'] == count
    assert not out['final_pipeline_search_count_known']
    assert out['final_pipeline_search_count'] is None
    assert not out['existing_semantic_findings_overridden']


@pytest.mark.parametrize('flag', [False, None, 'true'])
def test_known_flag_cannot_promote_an_early_result(proof, flag):
    out = assess_saved_count_stage({'news_result_count_known': flag, 'news_result_count': 3}, proof)
    assert out['status'] == 'UNKNOWN_AT_CAPTURE_STAGE'
    assert not out['o_single_stock_formal_acceptance']


def test_unknown_source_stage_is_explicit():
    out = assess_saved_count_stage({'news_result_count_known': True, 'news_result_count': None}, {})
    assert out['status'] == 'CAPTURE_STAGE_UNPROVEN'


def test_missing_field_is_distinct_from_explicit_null(proof):
    absent = assess_saved_count_stage({}, proof)
    null = assess_saved_count_stage({'news_result_count': None}, proof)
    assert not absent['native_fields']['news_result_count']['present']
    assert null['native_fields']['news_result_count']['present']


def test_inputs_are_immutable_and_repeatable(proof):
    result = {'action': 'watch', 'news_result_count': None, 'news_result_count_known': True,
              'dashboard': {'checklist': ['synthetic only']}}
    before = deepcopy((result, proof))
    a = assess_saved_count_stage(result, proof)
    b = assess_saved_count_stage(result, proof)
    assert a == b and (result, proof) == before
    assert a['source_result_mutated'] is False
    assert a['repeat_model_request_permitted'] is False
    assert a['runtime_activated'] is False
    assert a['new_model_requests'] == 0


@pytest.mark.parametrize('key,value', [('version', 'UNKNOWN'), ('status', 'FAIL'),
    ('source_sha256', {}), ('capture_stage', 'PIPELINE_FINAL')])
def test_unproven_provenance_fails_closed(proof, key, value):
    changed = deepcopy(proof); changed[key] = value
    out = assess_saved_count_stage({'news_result_count': 3}, changed)
    assert out['status'] == 'CAPTURE_STAGE_UNPROVEN'


def test_input_types_rejected():
    with pytest.raises(ValueError, match='MAPPING_REQUIRED'):
        assess_saved_count_stage([], {})
