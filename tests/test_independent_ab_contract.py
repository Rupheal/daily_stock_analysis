import datetime as dt,importlib.util,json,subprocess,tempfile
from decimal import Decimal
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
FA=ROOT/"audit_fixtures"/"foundation_pr40"

def loadmod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

rb=loadmod("rb",FA/"shared_resource_broker.py")
rc=loadmod("rc",FA/"resource_receipt_contract.py")
from src.services import dsa_resource_adapter as dsa

REG=json.loads((FA/"SHARED_RESOURCE_REGISTRY_v1.json").read_text())
NOW=dt.datetime.now(dt.timezone.utc)

def make_keys(root):
    private=root/"foundation-private.pem";public=root/"foundation-public.pem"
    subprocess.run(["openssl","genpkey","-algorithm","ED25519","-out",str(private)],check=True,capture_output=True)
    subprocess.run(["openssl","pkey","-in",str(private),"-pubout","-out",str(public)],check=True,capture_output=True)
    return private,public

def sign(private,input_path,signature):
    subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",str(private),
                    "-in",str(input_path),"-out",str(signature)],check=True,capture_output=True)

def test_foundation_claim_receipt_drives_dsa_schedule_without_local_global_authority(tmp_path,monkeypatch):
    state={"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},"budgets":{}}
    key=dsa.DurableResourceState.logical_cycle_key("2026-09-28","O","a"*64)
    state,claim=rb.acquire(REG,state,"SCHEDULE:DSA:DAILY_FORMAL","TRI-TASK-DSA-RUNTIME-P0",
                           "worker-A","JOB",NOW,600,purpose="O cycle",session_ref=key)
    receipt=rc.claim_receipt(claim,state);readback=rc.claim_readback(claim,state)
    rp=tmp_path/"claim.json";rbp=tmp_path/"readback.json";sig=tmp_path/"readback.sig"
    rp.write_text(json.dumps(receipt));rbp.write_text(json.dumps(readback))
    private,public=make_keys(tmp_path);sign(private,rbp,sig)
    monkeypatch.setattr(dsa,"FOUNDATION_TRUST_ROOT",public)
    verified=dsa.ResourceClaim.from_verified_artifacts(rp,rbp,sig)
    local=dsa.DurableResourceState(tmp_path/"state.db")
    first=local.begin_cycle(key,key,verified)
    assert first["action"]=="EXECUTE"
    assert local.begin_cycle(key,key,verified)["action"]=="ATTACH_WAIT"

def test_foundation_quota_reservation_is_consumed_without_local_reserve(tmp_path,monkeypatch):
    state={"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},
           "budgets":{"API:DEEPSEEK:DSA":{"available_units":10,"unit":"CNY"}}}
    state,row=rb.reserve_budget(REG,state,"API:DEEPSEEK:DSA","run-1",Decimal("2"),NOW,"RSV-DSA")
    expires=(NOW+dt.timedelta(minutes=10)).isoformat()
    receipt=rc.quota_reservation_receipt(row,state,expires_at=expires,idempotency_key="reserve:run-1")
    readback=rc.quota_reservation_readback(row,state,expires_at=expires,idempotency_key="reserve:run-1")
    rp=tmp_path/"reservation.json";rbp=tmp_path/"quota-readback.json";sig=tmp_path/"quota-readback.sig"
    rp.write_text(json.dumps(receipt));rbp.write_text(json.dumps(readback))
    private,public=make_keys(tmp_path);sign(private,rbp,sig)
    monkeypatch.setattr(dsa,"FOUNDATION_TRUST_ROOT",public)
    verified=dsa.FoundationReservation.from_verified_artifacts(rp,rbp,sig)
    local=dsa.DurableResourceState(tmp_path/"state.db")
    assert local.consume_foundation_reservation(verified,"consume","consume-1",Decimal("1"))=="PARTIALLY_CONSUMED"
    with pytest.raises(dsa.ResourceConflict,match="FOUNDATION_RESERVATION_PROOF_REQUIRED"):
        local.reserve_quota(dsa.ResourceClaim("API:DEEPSEEK:DSA","x","run",1),"r",Decimal("1"),"i")

def test_unverified_legacy_claim_never_authorizes_mutation(tmp_path):
    legacy={"resource_id":"GIT:DSA:NATIVE_PRIVATE_BRANCH","claim_id":"x","session_ref":"job",
            "task_id":"TRI-TASK-DSA-RUNTIME-P0","worker_id":"w","epoch":999999}
    parsed=dsa.ResourceClaim.from_dict(legacy)
    assert parsed.proof_verified is False
    with pytest.raises(dsa.ResourceConflict,match="FOUNDATION_CLAIM_PROOF_REQUIRED"):
        dsa.DurableResourceState(tmp_path/"state.db").validate_claim(parsed,"GIT:DSA:NATIVE_PRIVATE_BRANCH")

def test_manifest_is_bound_to_foundation_canonical_contract_and_registry_names():
    m=json.loads(Path("docs/runtime/DSA_RESOURCE_ADAPTER_MANIFEST_V1.json").read_text())
    assert m["foundation_contract"]["claim_schema"]=="foundation.resource-claim-receipt/v1"
    assert m["foundation_contract"]["quota_schema"]=="foundation.quota-reservation-receipt/v1"
    assert m["foundation_contract"]["schedule_job_id_binding"].startswith("job_id == logical_cycle_key")
    assert m["foundation_contract"]["caller_selectable_trust_root"] is False
    deps=set(m["shadow_factory"]["dependencies"])
    registry_ids={r["resource_id"] for r in REG["resources"]}
    assert deps<=registry_ids
