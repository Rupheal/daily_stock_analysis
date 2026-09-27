import argparse,datetime as dt,importlib.util,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/"audit_fixtures"/"neotutor_pr1"
spec=importlib.util.spec_from_file_location("neo_pr1",FIX/"neotutor_resource_adapter.py")
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

def foundation_claim():
    return {
      "claim_id":"RCL-foundation",
      "resource_id":"LOCAL:NEOTUTOR:ACCEPTANCE_RUNTIME",
      "task_id":"TRI-TASK-NEOTUTOR",
      "worker_id":"worker-A",
      "mode":"JOB","epoch":7,"purpose":"acceptance","session_ref":"job-A",
      "acquired_at":"2026-09-27T00:00:00Z",
      "heartbeat_at":"2026-09-27T00:00:00Z",
      "expires_at":"2099-09-27T00:10:00Z","ttl_seconds":600,
      "state":"ACTIVE","sessions":[],"handoff_state":"ACTIVE"
    }

class NeoTutorPR1Contract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_foundation_pr40_claim_is_directly_consumable(self):
        c=foundation_claim()
        ep={"resource_id":c["resource_id"],"claim_id":c["claim_id"],"epoch":c["epoch"]}
        a.validate_claim(c,ep,self.root/"workspace")

    def test_forged_verified_boolean_is_not_foundation_proof(self):
        now=dt.datetime.now(dt.timezone.utc)
        claim={"job_id":"evil","claim_id":"fake","resource_id":a.RESOURCE,"fencing_epoch":999999,
               "issued_at":(now-dt.timedelta(minutes=1)).isoformat(),
               "expires_at":(now+dt.timedelta(hours=1)).isoformat(),"verified":True}
        ep={"resource_id":a.RESOURCE,"claim_id":"fake","fencing_epoch":999999}
        with self.assertRaisesRegex(a.ResourceError,"FOUNDATION|PROOF|BROKER|SIGNATURE|RECEIPT"):
            a.validate_claim(claim,ep,self.root/"workspace")

    def test_local_quota_reserve_requires_foundation_reservation_proof(self):
        ns=argparse.Namespace(state_dir=str(self.root/"state"),operation="reserve",
            run_id="run",reservation_id="local-only",requested_units=5,units=0,idempotency_key="reserve")
        with self.assertRaisesRegex(a.ResourceError,"FOUNDATION|RESERVATION|PROOF|BROKER"):
            a.quota(ns)

    def test_stable_runtime_boundary_still_fails_closed(self):
        now=dt.datetime.now(dt.timezone.utc)
        claim={"job_id":"job","claim_id":"claim","resource_id":a.RESOURCE,"fencing_epoch":1,
               "issued_at":(now-dt.timedelta(minutes=1)).isoformat(),
               "expires_at":(now+dt.timedelta(hours=1)).isoformat(),"verified":True}
        ep={"resource_id":a.RESOURCE,"claim_id":"claim","fencing_epoch":1}
        with self.assertRaises(a.ResourceError):
            a.validate_claim(claim,ep,Path("/home/alienware/NeoTutor/subdir"))

if __name__=="__main__":unittest.main()
