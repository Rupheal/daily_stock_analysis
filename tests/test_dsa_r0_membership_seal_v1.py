import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("snap",ROOT/"scripts/dsa_daily_market_snapshot_v1.py")
snap=importlib.util.module_from_spec(spec);spec.loader.exec_module(snap)

def test_sealed_r0_snapshot_uses_no_future_identity(tmp_path):
    seal=tmp_path/"seal.json"
    seal.write_text(json.dumps({
      "status":"ACCEPTED_SAME_SESSION_R0_MEMBERSHIP_SEAL","target_session":"2026-09-21",
      "membership_code_count":2,"codes":["00001","03223"],"seal_id":"s",
      "source_workflow_run":1,"source_artifact_id":2,"source_artifact_digest":"sha256:x","source_universe_sha256":"u"
    }))
    prior=tmp_path/"prior.json"
    prior.write_text(json.dumps({"effective_session":"2026-09-17","members":[{"code":"00001","official_name":"A","security_type":"股票","channels":["SSE"],"board_lot":500,"isin":"x","currency":"HKD"}]}))
    u=tmp_path/"u.json"
    u.write_text(json.dumps({"member_count":45,"members":[{"code":str(i).zfill(5),"official_name":str(i)} for i in range(1,46)]}))
    out=tmp_path/"out";out.mkdir()
    r=snap.build_from_r0_seal("2026-09-21",u,prior,seal,out)
    assert r["mode"]=="R0_SEALED_SAME_SESSION"
    assert r["O_r0_denominator"]==2
    assert r["identity_pending_count"]==1
    assert r["paid_model_calls"]==0
    o=json.load(open(out/"O_R0_UNIVERSE.json"))
    assert o["formal_stock_universe_verified"] is False
    assert o["members"][1]["identity_status"]=="SEALED_MEMBERSHIP_IDENTITY_PENDING"

def test_seal_never_creates_formal_universe_files(tmp_path):
    src=(ROOT/"scripts/dsa_daily_market_snapshot_v1.py").read_text()
    assert "R0_SEALED_SAME_SESSION" in src
    assert "formal_universe_available':False" in src
