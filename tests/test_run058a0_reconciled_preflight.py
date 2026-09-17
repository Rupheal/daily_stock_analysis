import pytest
from scripts.run058a0_reconciled_preflight import finite_rows

def rows(n=21,target="2026-09-17"):
    from datetime import date,timedelta
    end=date.fromisoformat(target)
    ds=[end-timedelta(days=i) for i in range(n)][::-1]
    return [{"date":d.isoformat(),"open":10,"high":11,"low":9,"close":10.5,"volume":100} for d in ds]

def test_fresh_window_passes():
    assert len(finite_rows(rows(),"2026-09-17"))==21

def test_bad_geometry_blocks():
    x=rows();x[-1]["high"]=8
    with pytest.raises(ValueError,match="INVALID_BAR_GEOMETRY"):finite_rows(x,"2026-09-17")

def test_missing_target_blocks():
    x=rows();x[-1]["date"]="2026-09-16"
    with pytest.raises(ValueError,match="FRESH_WINDOW_INCOMPLETE"):finite_rows(x,"2026-09-17")
