"""Keep legacy 60-session gate; new pool path validates its complete native window."""
import sys
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from prepare_xiaomi_acceptance import compare_prices

def frame():
    return pd.DataFrame([{'date':d.strftime('%Y-%m-%d'),'open':10.,'high':11.,'low':9.,'close':10.,'volume':100.} for d in pd.bdate_range('2026-07-20',periods=43)])

def test_default_minimum_not_relaxed_and_whole_window_required():
    x=frame();target=x.iloc[-1]['date']
    with pytest.raises(ValueError,match='Incomplete'):compare_prices(x,x,target)
    assert compare_prices(x,x,target,minimum_overlap=43)==43
    with pytest.raises(ValueError):compare_prices(x,x.iloc[1:],target,minimum_overlap=43)
    y=x.copy();y.loc[0,'open']=10.1
    with pytest.raises(ValueError,match='PRICE_DISAGREEMENT_OPEN'):compare_prices(x,y,target,minimum_overlap=43)
