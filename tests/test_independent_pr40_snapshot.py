import importlib.util,json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/"audit_fixtures"/"foundation_pr40"
spec=importlib.util.spec_from_file_location("pr40_broker",FIX/"shared_resource_broker.py")
rb=importlib.util.module_from_spec(spec);spec.loader.exec_module(rb)
REG=json.loads((FIX/"SHARED_RESOURCE_REGISTRY_v1.json").read_text())
NOW=datetime(2026,9,27,tzinfo=timezone.utc)

def state():
    return {"schema_version":1,"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},"budgets":{}}

def test_pr40_quarantined_resource_cannot_be_regranted_before_finalizers():
    s,c=rb.acquire(REG,state(),"HOST:ALIENWARE:RUPHEAL","A","w1","JOB",NOW,60)
    s=rb.attach_session(s,c["resource_id"],c["claim_id"],c["epoch"],"PID-OLD","PROCESS",NOW)
    s=rb.quarantine_expired(s,NOW+timedelta(seconds=61))
    assert s["claims"][c["resource_id"]][0]["state"]=="QUARANTINED"
    s,r=rb.enqueue_request(REG,s,"B","w2","job2",
        [{"resource_id":"HOST:ALIENWARE:RUPHEAL","mode":"JOB","required":True,"purpose":"replacement"}],
        1,NOW+timedelta(seconds=62),"replacement")
    with pytest.raises(rb.ResourceConflict):
        rb.grant_request(REG,s,r["request_id"],NOW+timedelta(seconds=62))

def test_pr40_same_idempotency_key_with_different_request_is_conflict():
    s,r1=rb.enqueue_request(REG,state(),"A","w1","job1",
        [{"resource_id":"HOST:ALIENWARE:RUPHEAL","mode":"JOB","required":True,"purpose":"one"}],
        1,NOW,"same-key")
    with pytest.raises(rb.ResourceConflict):
        rb.enqueue_request(REG,s,"B","w2","job2",
            [{"resource_id":"GIT:FOUNDATION:REPAIR_BRANCH","mode":"WRITE","required":True,"purpose":"different"}],
            1,NOW,"same-key")

def test_pr40_runtime_cli_claim_path_calls_resource_gate():
    src=(FIX/"tri_task_runtime_cli.py").read_text()
    assert "prepare_resource_dispatch" in src
    assert "validate_resource_gate" in src

def test_pr40_supervisor_resource_heartbeat_is_wired_not_definition_only():
    src=(FIX/"tri_task_supervisor_v03.py").read_text()
    assert src.count("bind_resource_heartbeat(")>1
    assert "begin_drain(" in src

def test_pr40_watchdog_actively_advances_resource_queue():
    src=(FIX/"tri_watchdog_all.py").read_text()
    assert "promote_next(" in src
    assert "quarantine_expired(" in src
