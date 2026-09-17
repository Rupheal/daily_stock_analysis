import json
from pathlib import Path
from scripts.build_run058_o_rollout_controller_v2 import build, validate_ledger

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    return json.loads((ROOT/name).read_text())

def base():
    return load("docs/runtime/RUN057_O_NATIVE_PLAN.json"),load("docs/runtime/RUN058_SCOPE.json")

def test_original_stop_holds():
    plan,scope=base()
    row={"run_id":"x","micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE"}
    out=build(plan,scope,[row],"p","l")
    assert out["state"]=="HOLD_NO_CHILD"

def test_verified_append_only_resolution_advances_to_mb002():
    plan,scope=base()
    rows=[
      {"run_id":"old","micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE"},
      {"run_id":"new","micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE",
       "resolution_status":"RAW_GATE_BLOCK","resolution_verified":True,"resolution_run_id":"TRI-DSA-O-NATIVE-20260918-058H"}
    ]
    out=build(plan,scope,rows,"p","l")
    assert out["state"]=="READY_CHILD_ENVELOPE"
    assert out["selected_child"]["micro_batch_id"]=="O57-MB-002"
    assert out["selected_child"]["codes"]==["00003","00004"]
    assert out["selected_child"]["provider_send_authorized_by_run058"] is False

def test_resolution_cannot_rewrite_status():
    plan,_=base()
    rows=[
      {"micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE"},
      {"micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"RAW_GATE_BLOCK",
       "resolution_status":"RAW_GATE_BLOCK","resolution_verified":True,"resolution_run_id":"x"}
    ]
    try: validate_ledger(rows,plan)
    except ValueError as e: assert "CONFLICTING_STATE" in str(e)
    else: raise AssertionError("must fail")

def test_unverified_resolution_fails_closed():
    plan,_=base()
    rows=[
      {"micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE"},
      {"micro_batch_id":"O57-MB-001","codes":["00001","00002"],"status":"STOP_TRANCHE",
       "resolution_status":"RAW_GATE_BLOCK","resolution_verified":False,"resolution_run_id":"x"}
    ]
    try: validate_ledger(rows,plan)
    except ValueError as e: assert "UNVERIFIED_RESOLUTION" in str(e)
    else: raise AssertionError("must fail")
