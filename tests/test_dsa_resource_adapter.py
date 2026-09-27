from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import subprocess

import pytest

from src.services.dsa_resource_adapter import (
    DurableResourceState, ResourceClaim, ResourceConflict, git_cas_push,
)


def claim(resource, epoch=1, run="run-1", claim_id="claim-1"):
    return ResourceClaim(resource, claim_id, run, epoch)


def test_logical_cycle_duplicate_transports_single_side_effect(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    key=state.logical_cycle_key("2026-09-28","O","a"*64)
    owner_claim=claim("SCHEDULE:DSA:DAILY_FORMAL",run="logical-owner")
    def trigger(n): return state.begin_cycle(key,"logical-owner",owner_claim)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(trigger,["schedule","push","manual"]))
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
    assert json.loads(pointer.read_text())==newer
    assert len(list(receipts.glob("*.json")))==2


def test_stale_fence_and_same_epoch_different_claim_fail_closed(tmp_path):
    state=DurableResourceState(tmp_path/"state.db")
    state.validate_claim(claim("DRIVE:DSA:SIMULATION_JOURNAL",2,claim_id="new"),"DRIVE:DSA:SIMULATION_JOURNAL")
    with pytest.raises(ResourceConflict,match="STALE_FENCING_EPOCH"):
        state.validate_claim(claim("DRIVE:DSA:SIMULATION_JOURNAL",1,claim_id="old"),"DRIVE:DSA:SIMULATION_JOURNAL")
    with pytest.raises(ResourceConflict,match="FENCING_EPOCH_CLAIM_CONFLICT"):
        state.validate_claim(claim("DRIVE:DSA:SIMULATION_JOURNAL",2,claim_id="other"),"DRIVE:DSA:SIMULATION_JOURNAL")


def test_paid_quota_concurrent_7_and_4_cannot_double_spend(tmp_path):
    state=DurableResourceState(tmp_path/"state.db"); state.configure_quota("API:DEEPSEEK:DSA",Decimal("10"))
    def reserve(n):
        try:
            return state.reserve_quota(claim("API:DEEPSEEK:DSA"),f"r{n}",Decimal(n),f"i{n}")["state"]
        except ResourceConflict as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(reserve,[7,4]))
    assert sorted(results)==["QUOTA_INSUFFICIENT","RESERVED"]


def test_paid_quota_consume_release_expire_and_idempotency(tmp_path):
    state=DurableResourceState(tmp_path/"state.db"); grant=claim("API:DEEPSEEK:DSA")
    state.configure_quota("API:DEEPSEEK:DSA",Decimal("10"))
    for suffix,operation in (("c","consume"),("r","release"),("e","expire")):
        rid=f"reservation-{suffix}"
        state.reserve_quota(grant,rid,Decimal("2"),f"reserve-{suffix}")
        expected={"consume":"CONSUMED","release":"RELEASED","expire":"EXPIRED"}[operation]
        assert state.settle_quota(grant,rid,operation,f"settle-{suffix}",Decimal("1"))==expected
        assert state.settle_quota(grant,rid,operation,f"settle-{suffix}",Decimal("1"))==expected


def _git(repo,*args):
    return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()


def test_git_writer_collision_only_one_non_force_push_succeeds(tmp_path):
    remote=tmp_path/"remote.git"; subprocess.check_call(["git","init","--bare",remote])
    seed=tmp_path/"seed"; subprocess.check_call(["git","init",seed]); _git(seed,"config","user.email","test@example.invalid"); _git(seed,"config","user.name","test")
    (seed/"base").write_text("base"); _git(seed,"add","base"); _git(seed,"commit","-m","base"); base=_git(seed,"rev-parse","HEAD")
    _git(seed,"push",str(remote),"HEAD:refs/heads/shared")
    commits=[]
    for name in ("one","two"):
        _git(seed,"checkout","--detach",base); (seed/name).write_text(name); _git(seed,"add",name); _git(seed,"commit","-m",name)
        commits.append((_git(seed,"rev-parse","HEAD"),_git(seed,"show","-s","--format=%T","HEAD")))
    state=DurableResourceState(tmp_path/"state.db"); grant=claim("GIT:DSA:NATIVE_PRIVATE_BRANCH")
    assert git_cas_push(seed,str(remote),"refs/heads/shared",base,*commits[0],grant,state)["force"]=="false"
    with pytest.raises(ResourceConflict,match="GIT_OBSERVED_BASE_CONFLICT"):
        git_cas_push(seed,str(remote),"refs/heads/shared",base,*commits[1],grant,state)


def test_manifest_declares_all_required_resources():
    manifest=json.loads(Path("docs/runtime/DSA_RESOURCE_ADAPTER_MANIFEST_V1.json").read_text())
    ids={x["id"] for x in manifest["resources"]}
    assert ids=={"GIT:DSA:NATIVE_PRIVATE_BRANCH","GIT:DSA:RUNTIME_SHADOW_JOURNAL",
                 "DRIVE:DSA:EVIDENCE_FOLDER","DRIVE:DSA:SIMULATION_JOURNAL",
                 "GIT:DSA:FORMAL_LATEST_POINTERS","SCHEDULE:DSA:DAILY_FORMAL","API:DEEPSEEK:DSA"}
    assert not manifest["production_enabled"] and not manifest["real_orders_enabled"]
