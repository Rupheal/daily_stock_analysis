from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import pytest
from src.services.dsa_resource_adapter import (
    DurableResourceState, ResourceClaim, ResourceConflict, FoundationReservation, git_cas_push,
)

def claim(resource, epoch=1, run="run-1", claim_id="claim-1"):
    return ResourceClaim(resource,claim_id,run,epoch,"task-1","worker-1","proof-hash",True)

def test_unproven_claim_waits_instead_of_executing(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    key=state.logical_cycle_key("2026-09-28","O","a"*64)
    unproven=ResourceClaim("SCHEDULE:DSA:DAILY_FORMAL","claim","run",1)
    assert state.begin_cycle(key,"run",unproven)["action"]=="WAIT_FOUNDATION_GRANT"

def test_proven_logical_cycle_local_idempotency(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    key=state.logical_cycle_key("2026-09-28","O","a"*64)
    owner_claim=claim("SCHEDULE:DSA:DAILY_FORMAL",run="logical-owner")
    def trigger(_): return state.begin_cycle(key,"logical-owner",owner_claim)
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(trigger,range(3)))
    assert [x["action"] for x in results].count("EXECUTE")==1
    owner=next(x["owner_run_id"] for x in results if x["action"]=="EXECUTE")
    state.complete_cycle(key,owner,{"artifact":"immutable"})
    assert state.begin_cycle(key,"logical-owner",owner_claim)["action"]=="NOOP"

def test_latest_old_delayed_run_cannot_overwrite_new(tmp_path):
    state=DurableResourceState(tmp_path/"state.db"); pointer=tmp_path/"LATEST.json"
    newer={"target_session":"2026-09-28","generation":2,"source_hash":"b"*64}
    older={"target_session":"2026-09-27","generation":99,"source_hash":"a"*64}
    receipts=tmp_path/"receipts"; grant=claim("GIT:DSA:FORMAL_LATEST_POINTERS")
    assert state.publish_projection(receipts,pointer,newer,grant)=="LATEST_ADVANCED"
    assert state.publish_projection(receipts,pointer,older,grant)=="STALE_RECEIPT_PRESERVED"
    assert json.loads(pointer.read_text())==newer and len(list(receipts.glob("*.json")))==2

def test_unproven_fence_fails_closed(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    with pytest.raises(ResourceConflict,match="FOUNDATION_CLAIM_PROOF_REQUIRED"):
        state.validate_claim(ResourceClaim("DRIVE:DSA:SIMULATION_JOURNAL","x","run",999999),
                             "DRIVE:DSA:SIMULATION_JOURNAL")

def test_local_quota_reserve_disabled(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    with pytest.raises(ResourceConflict,match="FOUNDATION_GLOBAL_QUOTA_AUTHORITY_REQUIRED"):
        state.configure_quota("API:DEEPSEEK:DSA",Decimal("10"))
    with pytest.raises(ResourceConflict,match="FOUNDATION_RESERVATION_PROOF_REQUIRED"):
        state.reserve_quota(claim("API:DEEPSEEK:DSA"),"r",Decimal("1"),"i")

def test_foundation_reservation_consumption_is_local_idempotent(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    reservation=FoundationReservation("API:DEEPSEEK:DSA","run","r",Decimal("2"),"reserve","hash",True)
    assert state.consume_foundation_reservation(reservation,"consume","consume-1",Decimal("1"))=="PARTIALLY_CONSUMED"
    assert state.consume_foundation_reservation(reservation,"consume","consume-1",Decimal("1"))=="PARTIALLY_CONSUMED"
    assert state.consume_foundation_reservation(reservation,"consume","consume-2",Decimal("1"))=="CONSUMED"

def _git(repo,*args): return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()
def test_git_writer_collision_only_one_non_force_push_succeeds(tmp_path):
    remote=tmp_path/"remote.git"; subprocess.check_call(["git","init","--bare",remote])
    seed=tmp_path/"seed"; subprocess.check_call(["git","init",seed]);_git(seed,"config","user.email","test@example.invalid");_git(seed,"config","user.name","test")
    (seed/"base").write_text("base");_git(seed,"add","base");_git(seed,"commit","-m","base");base=_git(seed,"rev-parse","HEAD");_git(seed,"push",str(remote),"HEAD:refs/heads/shared")
    commits=[]
    for name in ("one","two"):
        _git(seed,"checkout","--detach",base);(seed/name).write_text(name);_git(seed,"add",name);_git(seed,"commit","-m",name)
        commits.append((_git(seed,"rev-parse","HEAD"),_git(seed,"show","-s","--format=%T","HEAD")))
    state=DurableResourceState(tmp_path/"state.db");grant=claim("GIT:DSA:NATIVE_PRIVATE_BRANCH")
    assert git_cas_push(seed,str(remote),"refs/heads/shared",base,*commits[0],grant,state)["force"]=="false"
    with pytest.raises(ResourceConflict,match="GIT_OBSERVED_BASE_CONFLICT"):
        git_cas_push(seed,str(remote),"refs/heads/shared",base,*commits[1],grant,state)

def test_manifest_declares_canonical_resources_only():
    m=json.loads(Path("docs/runtime/DSA_RESOURCE_ADAPTER_MANIFEST_V1.json").read_text())
    ids={x["id"] for x in m["resources"]}
    assert ids=={"GIT:DSA:NATIVE_PRIVATE_BRANCH","GIT:DSA:RUNTIME_SHADOW_JOURNAL",
                 "DRIVE:DSA:EVIDENCE_FOLDER","DRIVE:DSA:SIMULATION_JOURNAL",
                 "GIT:DSA:FORMAL_LATEST_POINTERS","SCHEDULE:DSA:DAILY_FORMAL","API:DEEPSEEK:DSA"}
    assert "RUNNER:DSA:SELF_HOSTED_OR_DC" not in m["shadow_factory"]["dependencies"]
    assert "IDENTITY:DSA:CANDIDATE" not in m["shadow_factory"]["dependencies"]
    assert not m["production_enabled"] and not m["real_orders_enabled"]
