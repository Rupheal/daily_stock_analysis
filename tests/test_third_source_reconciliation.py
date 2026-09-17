from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from reconcile_hk_third_source import whole_window_agrees


def rows():
    return [dict(date=f'2026-08-{x:02}',open=10.,high=11.,low=9.,close=10.,volume=100.) for x in range(1,22)]


def test_complete_window_passes_but_open_or_volume_conflict_does_not():
    a=rows();b=rows();assert whole_window_agrees(a,b,'2026-08-21')['accepted']
    b[3]['open']=10.5;assert not whole_window_agrees(a,b,'2026-08-21')['accepted']
    b=rows();b[0]['volume']=101;assert not whole_window_agrees(a,b,'2026-08-21')['accepted']


def test_missing_target_and_different_dates_are_rejected():
    a=rows();assert not whole_window_agrees(a,a[:-1],'2026-08-21')['accepted']
    b=rows();b[0]['date']='2026-07-31';assert not whole_window_agrees(a,b,'2026-08-21')['accepted']
