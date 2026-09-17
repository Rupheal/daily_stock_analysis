import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from apply_run006_current_recovery import raw_agreement

def test_existing_raw_bound_and_volume_not_expanded():
    x=[dict(date=f'2026-08-{i:02}',open=10.,high=11.,low=9.,close=10.,volume=100.) for i in range(1,22)];y=[dict(r) for r in x]
    assert raw_agreement(x,y,'2026-08-21')['class']=='RAW_PRICE_AGREEMENT_TIGHT'
    y[0]['open']=10.015
    assert raw_agreement(x,y,'2026-08-21')['class']=='RAW_PRICE_AGREEMENT_LOOSE'
    y[0]['volume']=101.
    assert not raw_agreement(x,y,'2026-08-21')['exact_volume_agreement']
    y[0]['open']=10.03
    assert raw_agreement(x,y,'2026-08-21')['class']=='RAW_SOURCE_CONFLICT'

def test_missing_target_stays_incomplete():
    assert raw_agreement([],[],'2026-09-16')['class']=='RAW_WINDOW_INCOMPLETE'
