import argparse,datetime as dt,importlib.util,json,subprocess,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FA=ROOT/"audit_fixtures"/"foundation_ac"
NC=ROOT/"audit_fixtures"/"neotutor_c"

def loadmod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

rb=loadmod("rb",FA/"shared_resource_broker.py")
rc=loadmod("rc",FA/"resource_receipt_contract.py")
neo=loadmod("neo",NC/"neotutor_resource_adapter.py")
REG=json.loads((FA/"SHARED_RESOURCE_REGISTRY_v1.json").read_text())
NOW=dt.datetime.now(dt.timezone.utc)

def sign(private_key,input_path,signature_path):
    subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",str(private_key),
                    "-in",str(input_path),"-out",str(signature_path)],check=True,capture_output=True)

def make_keys(root):
    private=root/"foundation-private.pem"; public=root/"foundation-public.pem"
    subprocess.run(["openssl","genpkey","-algorithm","ED25519","-out",str(private)],check=True,capture_output=True)
    subprocess.run(["openssl","pkey","-in",str(private),"-pubout","-out",str(public)],check=True,capture_output=True)
    return private,public

def test_foundation_claim_receipt_is_consumed_by_neotutor_preflight(tmp_path,monkeypatch):
    state={"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},"budgets":{}}
    state,claim=rb.acquire(REG,state,"LOCAL:NEOTUTOR:ACCEPTANCE_RUNTIME",
                           "TRI-TASK-NEOTUTOR","worker-A","JOB",NOW,600,
                           purpose="acceptance",session_ref="job-A")
    receipt=rc.claim_receipt(claim,state)
    readback=rc.claim_readback(claim,state)
    claim_path=tmp_path/"claim.json"; rb_path=tmp_path/"readback.json"; sig=tmp_path/"readback.sig"
    claim_path.write_text(json.dumps(receipt))
    rb_path.write_text(json.dumps(readback))
    private,public=make_keys(tmp_path); sign(private,rb_path,sig)
    monkeypatch.setattr(neo,"FOUNDATION_TRUST_ROOT",public)
    ns=argparse.Namespace(
        claim_receipt=str(claim_path),foundation_readback=str(rb_path),
        foundation_readback_signature=str(sig),workspace=str(tmp_path/"NeoTutor-dev"),
        state_dir=str(tmp_path/"state"),backend_port=[],frontend_port=[],container=[])
    rec=neo.preflight(ns)
    assert rec["claim_id"]==claim["claim_id"]
    assert rec["fencing_epoch"]==claim["epoch"]
    assert rec["task_id"]=="TRI-TASK-NEOTUTOR"
    assert rec["worker_id"]=="worker-A"
    assert rec["job_id"]=="job-A"
    assert rec["stable_runtime_touched"] is False

def test_foundation_quota_receipt_is_consumed_by_neotutor_without_local_reserve(tmp_path,monkeypatch):
    state={"next_epoch":1,"claims":{},"requests":{},"queue":[],"reservations":{},
           "budgets":{"API:OPENAI:NEOTUTOR":{"available_units":3,"unit":"TURN"}}}
    state,row=rb.reserve_budget(REG,state,"API:OPENAI:NEOTUTOR","run-1",1,NOW,"RSV-1")
    expires=(NOW+dt.timedelta(minutes=10)).isoformat()
    receipt=rc.quota_reservation_receipt(row,state,expires_at=expires,idempotency_key="reserve:run-1")
    readback=rc.quota_reservation_readback(row,state,expires_at=expires,idempotency_key="reserve:run-1")
    rp=tmp_path/"reservation.json"; rbp=tmp_path/"quota-readback.json"; sig=tmp_path/"quota-readback.sig"
    rp.write_text(json.dumps(receipt)); rbp.write_text(json.dumps(readback))
    private,public=make_keys(tmp_path); sign(private,rbp,sig)
    monkeypatch.setattr(neo,"FOUNDATION_TRUST_ROOT",public)
    ns=argparse.Namespace(
      state_dir=str(tmp_path/"state"),operation="consume",
      reservation_receipt=str(rp),foundation_readback=str(rbp),
      foundation_readback_signature=str(sig),units=1,idempotency_key="consume-1")
    out=neo.quota(ns)
    assert out["reservation_id"]=="RSV-1"
    assert out["consumed_units"]==1
    assert out["state"]=="RESERVED"

def test_neotutor_cli_exposes_no_local_quota_reserve_operation():
    p=neo.parser()
    try:
        p.parse_args(["quota","reserve","--reservation-receipt","x","--foundation-readback","y",
                      "--foundation-readback-signature","z","--idempotency-key","i"])
    except SystemExit:
        return
    raise AssertionError("local reserve operation unexpectedly accepted")

def test_manifest_matches_foundation_contract_names():
    m=json.loads((NC/"neotutor-resource-adapter.json").read_text())
    assert m["canonical_claim_schema"]=="foundation.resource-claim-receipt/v1"
    assert m["foundation_contract"]["canonical_readback_schema"]=="foundation.resource-claim-readback/v1"
    assert m["openai_quota"]["receipt_schema"]=="foundation.quota-reservation-receipt/v1"
