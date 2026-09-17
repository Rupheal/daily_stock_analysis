import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_dual_history_cache import normalized,compare

def bars():
    return [dict(date=f'2026-08-{i:02}',open=10,close=11,low=9,high=12,volume=1000) for i in range(1,25)]

def test_future_and_duplicate_fail_closed():
    with pytest.raises(ValueError,match='FUTURE'):normalized(bars(),'2026-08-23')
    with pytest.raises(ValueError,match='DUPLICATE'):normalized(bars()+[bars()[-1]],'2026-08-24')

def test_identical_recovery_provider_is_not_independent():
    x=normalized(bars(),'2026-08-24');assert not compare(x,x,'2026-08-24',False)['independent_history_passed']
    assert compare(x,x,'2026-08-24')['independent_history_passed']

def test_history_disagreement_not_hidden_by_last_bar():
    x=normalized(bars(),'2026-08-24');y=normalized(bars(),'2026-08-24');y[0]['volume']=1001
    assert 'VOLUME_DISAGREEMENT' in compare(x,y,'2026-08-24')['failures']
    y[0]['open']=10.1
    assert 'OHLC_OR_ADJUSTMENT_DISAGREEMENT' in compare(x,y,'2026-08-24')['failures']
