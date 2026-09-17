import sys,struct
from decimal import Decimal
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from o_release_quote_semantics import _sanitize_current_price_fields, ReleaseQuoteError


def test_only_exact_proven_native_float32_representation_is_cleared():
    close=Decimal('29.66');native=Decimal(str(struct.unpack('!f',struct.pack('!f',float(close)))[0]))
    row={'current_price':float(native),'sentiment_score':65}
    changes=_sanitize_current_price_fields(row,target_close=close,native_close=native)
    assert row=={'current_price':None,'sentiment_score':65}
    assert changes[0]['numeric_basis']=='exact_native_input_float32_representation'


@pytest.mark.parametrize('price,native',[(29.65,29.65),(29.66001,29.66001),(29.65999984741211,None),(29.65999984741211,29.66)])
def test_close_enough_or_unproven_value_is_not_accepted(price,native):
    with pytest.raises(ReleaseQuoteError):
        _sanitize_current_price_fields({'current_price':price},target_close=Decimal('29.66'),
            native_close=Decimal(str(native)) if native is not None else None)
