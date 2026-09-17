import json, pytest
from scripts.run058a0_fresh_preflight import validate_native_rows,pit_members

def bars(n=21,target="2026-09-17"):
    from datetime import date,timedelta
    end=date.fromisoformat(target)
    days=[end-timedelta(days=i) for i in range(n)][::-1]
    return [{"date":d.isoformat(),"open":10.0,"high":11.0,"low":9.0,"close":10.5,"volume":1000.0} for d in days]

def universe():
    members=[{"code":f"{i:05d}","channels":["SSE"]} for i in range(1,661)]
    members[0]["code"]="00001";members[1]["code"]="00002"
    return {"full_union_verified":True,"effective_session":"2026-09-17","member_count":660,
            "observed_at_utc":"2026-09-17T03:11:29+00:00","members":members}

def test_21_bar_geometry_pass():
    assert len(validate_native_rows(bars(), "2026-09-17"))==21

def test_less_than_21_fails():
    with pytest.raises(ValueError,match="LESS_THAN_21_BARS"):
        validate_native_rows(bars(20),"2026-09-17")

def test_bad_geometry_fails():
    x=bars();x[-1]["low"]=12
    with pytest.raises(ValueError,match="INVALID_BAR_GEOMETRY"):
        validate_native_rows(x,"2026-09-17")

def test_target_missing_fails():
    x=bars();x[-1]["date"]="2026-09-16"
    with pytest.raises(ValueError):
        validate_native_rows(x,"2026-09-17")

def test_pit_members_pass():
    got=pit_members(universe(),"2026-09-17","2026-09-18")
    assert set(got)=={"00001","00002"}

def test_wrong_pit_session_fails():
    u=universe();u["effective_session"]="2026-09-16"
    with pytest.raises(ValueError,match="PIT_EFFECTIVE_SESSION_MISMATCH"):
        pit_members(u,"2026-09-17","2026-09-18")

def test_future_pit_availability_fails():
    u=universe();u["observed_at_utc"]="2026-09-17T09:00:00+00:00"
    with pytest.raises(ValueError,match="PIT_UNIVERSE_FUTURE_AVAILABLE"):
        pit_members(u,"2026-09-17","2026-09-18")
