from decimal import Decimal
import pytest

from deepseek_flash_cap010_guard import (
    HARD_CAP_CNY, DEFAULT_INPUT_MARGIN_TOKENS, peak_upper_cny,
)


def test_historical_shape_with_margin_remains_below_cap():
    # Historical CHILD2 actual provider prompt_tokens=4687. This test does not
    # assume Run028 has the same prompt; Run028 must count its concrete request.
    assert peak_upper_cny(4687, 8192) < HARD_CAP_CNY


def test_cap_boundary_is_exact_and_fail_closed_ready():
    # With 8192 max output and a 2048-token safety margin, the largest counted
    # input that fits the 0.10 CNY peak envelope is 15184 tokens.
    assert peak_upper_cny(15184, 8192) == Decimal('0.100000')
    assert peak_upper_cny(15185, 8192) > HARD_CAP_CNY


def test_bad_counts_rejected():
    for value in (-1, 1.5, True):
        with pytest.raises(ValueError):
            peak_upper_cny(value, 8192)
    with pytest.raises(ValueError):
        peak_upper_cny(1, 0)
    with pytest.raises(ValueError):
        peak_upper_cny(1, 8192, margin_tokens=-1)


def test_default_margin_is_2048():
    assert DEFAULT_INPUT_MARGIN_TOKENS == 2048
