import json
from pathlib import Path
import pytest
from src.services.dsa_resource_adapter import DurableResourceState,ResourceClaim,ResourceConflict

A_REGISTRY_IDS={
"HOST:ALIENWARE:RUPHEAL","DEVICE:REMOTE_DESKTOP_COMMANDER:RUPHEAL",
"RUNNER:GITHUB:TRIDENT-ALIENWARE","RUNNER:GITHUB:TRIDENT-SEC-ALIENWARE",
"GIT:FOUNDATION:MAIN:TASK_BUS","GIT:FOUNDATION:REPAIR_BRANCH",
"GIT:DSA:NATIVE_PRIVATE_BRANCH","GIT:DSA:RUNTIME_SHADOW_JOURNAL",
"DRIVE:DSA:EVIDENCE_FOLDER","DRIVE:DSA:SIMULATION_JOURNAL",
"LOCAL:NEOTUTOR:ACCEPTANCE_RUNTIME","API:DEEPSEEK:DSA","API:OPENAI:NEOTUTOR",
"CHATGPT:AUTOMATIONS:TASK_SET","GIT:DSA:FORMAL_LATEST_POINTERS","SCHEDULE:DSA:DAILY_FORMAL"
}

def foundation_claim(resource="GIT:DSA:NATIVE_PRIVATE_BRANCH",epoch=7):
    # Exact field family emitted by Foundation PR40 shared_resource_broker.acquire().
    return {
      "claim_id":"RCL-foundation","resource_id":resource,
      "task_id":"TRI-TASK-DSA-RUNTIME-P0","worker_id":"worker-A",
      "mode":"WRITE","epoch":epoch,"purpose":"test","session_ref":"job-A",
      "acquired_at":"2026-09-27T00:00:00Z","heartbeat_at":"2026-09-27T00:00:00Z",
      "expires_at":"2026-09-27T00:10:00Z","ttl_seconds":600,
      "state":"ACTIVE","sessions":[],"handoff_state":"ACTIVE"
    }

def test_foundation_pr40_claim_is_directly_consumable_by_dsa_adapter():
    ResourceClaim.from_dict(foundation_claim())

def test_shadow_factory_dependencies_are_registered_foundation_resources():
    m=json.loads(Path("docs/runtime/DSA_RESOURCE_ADAPTER_MANIFEST_V1.json").read_text())
    missing=set(m["shadow_factory"]["dependencies"])-A_REGISTRY_IDS
    assert not missing,sorted(missing)

def test_adapter_does_not_accept_unproven_high_epoch_as_foundation_truth(tmp_path):
    state=DurableResourceState(tmp_path/"adapter.db")
    forged=ResourceClaim("GIT:DSA:NATIVE_PRIVATE_BRANCH","forged","forged-run",999999)
    with pytest.raises(ResourceConflict,match="PROOF|FOUNDATION|BROKER|CLAIM"):
        state.validate_claim(forged,"GIT:DSA:NATIVE_PRIVATE_BRANCH")

def test_local_sqlite_singleflight_is_not_global_across_two_hosts(tmp_path):
    a=DurableResourceState(tmp_path/"host-a.db")
    b=DurableResourceState(tmp_path/"host-b.db")
    key=a.logical_cycle_key("2026-09-28","O","a"*64)
    claim=ResourceClaim("SCHEDULE:DSA:DAILY_FORMAL","claim","run",1)
    ra=a.begin_cycle(key,"run",claim)
    rb=b.begin_cycle(key,"run",claim)
    # This documents the unresolved Foundation dependency: separate adapter DBs both execute.
    assert not (ra["action"]=="EXECUTE" and rb["action"]=="EXECUTE"),(ra,rb)
