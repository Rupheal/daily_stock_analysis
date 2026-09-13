import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('runner_v2', ROOT/'scripts/run004_u45_safe_deepseek_v2.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


def valid(**extra):
    value = {
        'score': 61,
        'stance': 'positive',
        'confidence': 'medium',
        'reason_codes': ['positive_momentum', 'trend_above_mas'],
    }
    value.update(extra)
    return value


def test_extra_model_keys_are_discarded_not_persisted():
    output = runner.validate_model_result_required_subset(valid(analysis='free text', explanation='discard me'))
    assert output == {
        'score': 61,
        'stance': 'positive',
        'confidence': 'medium',
        'reason_codes': ['positive_momentum', 'trend_above_mas'],
    }
    assert 'analysis' not in output and 'explanation' not in output


def test_missing_required_field_still_fails_closed():
    value = valid(); value.pop('confidence')
    with pytest.raises(ValueError, match='missing_required'):
        runner.validate_model_result_required_subset(value)


def test_illegal_required_values_are_not_relaxed():
    with pytest.raises(ValueError, match='invalid_score'):
        runner.validate_model_result_required_subset(valid(score=101))
    with pytest.raises(ValueError, match='unknown_reason_code'):
        runner.validate_model_result_required_subset(valid(reason_codes=['invented_reason']))
