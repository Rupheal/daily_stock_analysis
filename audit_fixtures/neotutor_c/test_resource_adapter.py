import argparse
import datetime as dt
from decimal import Decimal
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import neotutor_resource_adapter as adapter

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.private_key=self.root/"foundation-private.pem"; self.public_key=self.root/"foundation-public.pem"
        subprocess.run(["openssl","genpkey","-algorithm","ED25519","-out",str(self.private_key)],check=True,capture_output=True)
        subprocess.run(["openssl","pkey","-in",str(self.private_key),"-pubout","-out",str(self.public_key)],check=True,capture_output=True)
        self.trust_root=mock.patch.object(adapter,"FOUNDATION_TRUST_ROOT",self.public_key); self.trust_root.start()
        now = dt.datetime.now(dt.timezone.utc)
        expires=(now+dt.timedelta(hours=1)).isoformat()
        self.claim = {"schema":"foundation.resource-claim-receipt/v1", "claim_id":"claim-1", "resource_id":adapter.RESOURCE,
            "holder":{"task_id":"task-1","worker_id":"worker-1","job_id":"job-1"}, "fencing_epoch":7,
            "acquired_at":(now-dt.timedelta(minutes=1)).isoformat(), "expires_at":expires,
            "broker_state":{"version":12,"hash":"broker-hash-12"}}
        self.readback = {"schema":"foundation.resource-claim-readback/v1", "state":"ACTIVE", **{k:self.claim[k] for k in
            ("claim_id","resource_id","holder","fencing_epoch","expires_at","broker_state")}}
        (self.root/"claim.json").write_text(json.dumps(self.claim)); self.write_readback()
    def tearDown(self): self.trust_root.stop(); self.tmp.cleanup()
    def args(self, **kw):
        values=dict(claim_receipt=str(self.root/"claim.json"), foundation_readback=str(self.root/"readback.json"),
                    foundation_readback_signature=str(self.root/"readback.sig"),
                    workspace=str(self.root/"workspace"),
                    state_dir=str(self.root/"state"), backend_port=[], frontend_port=[], container=[])
        values.update(kw); return argparse.Namespace(**values)
    def write_readback(self):
        path=self.root/"readback.json"; path.write_text(json.dumps(self.readback))
        subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",str(self.private_key),"-in",str(path),
                        "-out",str(self.root/"readback.sig")],check=True,capture_output=True)
    def test_preflight_and_cleanup_preserve_stable_boundary(self):
        rec=adapter.preflight(self.args())
        self.assertFalse(rec["stable_runtime_touched"])
        out=adapter.cleanup(argparse.Namespace(state_dir=str(self.root/"state"), claim_id="claim-1"))
        self.assertEqual(out["state"], "RELEASED"); self.assertFalse(out["stable_runtime_touched"])
    def test_stale_fence_fails_closed(self):
        self.claim["fencing_epoch"]=8; self.readback["fencing_epoch"]=8
        (self.root/"claim.json").write_text(json.dumps(self.claim)); (self.root/"readback.json").write_text(json.dumps(self.readback))
        with self.assertRaisesRegex(adapter.ResourceError, "FOUNDATION_PROOF_INVALID"): adapter.preflight(self.args())
    def test_live_port_conflict_does_not_kill_owner(self):
        with socket.socket() as owner:
            owner.bind(("127.0.0.1",0)); port=owner.getsockname()[1]
            with self.assertRaisesRegex(adapter.ResourceError, "RESOURCE_CONFLICT"): adapter.preflight(self.args(backend_port=[port]))
            owner.getsockname()  # still alive
    def test_second_claim_cannot_take_claimed_port(self):
        adapter.preflight(self.args(backend_port=[34567]))
        self.claim["holder"]["job_id"]="job-2"; self.claim["claim_id"]="claim-2"
        self.readback.update(claim_id="claim-2", holder=self.claim["holder"]); self.write_readback()
        (self.root/"claim.json").write_text(json.dumps(self.claim))
        with self.assertRaisesRegex(adapter.ResourceError, "RESOURCE_CONFLICT"): adapter.preflight(self.args(backend_port=[34567]))
    @mock.patch.object(adapter, "docker_record")
    @mock.patch.object(adapter.shutil, "which", return_value="/usr/bin/docker")
    def test_foreign_container_is_quarantined_not_removed(self, _which, inspect):
        inspect.return_value={"container_id":"abc", "job_id":"foreign", "claim_id":"other", "fencing_epoch":"7"}
        with self.assertRaisesRegex(adapter.ResourceError, "QUARANTINE_REQUIRED"): adapter.preflight(self.args(container=["shared-name"]))
    def test_pid_identity_mismatch_is_not_killed(self):
        adapter.preflight(self.args())
        with adapter.locked_state(self.root/"state") as ledger:
            ledger["claims"]["claim-1"]["pids"]=[{"pid":os.getpid(), "start_ticks":"wrong", "executable":"wrong"}]
        with mock.patch.object(adapter.os, "kill") as kill:
            with self.assertRaisesRegex(adapter.ResourceError, "quarantined"): adapter.cleanup(argparse.Namespace(state_dir=str(self.root/"state"), claim_id="claim-1"))
            kill.assert_not_called()
        ledger=json.loads((self.root/"state"/"ledger.json").read_text())
        self.assertEqual(ledger["claims"]["claim-1"]["state"], "QUARANTINED")
    def test_quota_is_atomic_idempotent_and_bounded(self):
        now=dt.datetime.now(dt.timezone.utc); expires=(now+dt.timedelta(hours=1)).isoformat()
        receipt={"schema":"foundation.quota-reservation-receipt/v1", "resource_id":adapter.QUOTA_RESOURCE,
                 "run_id":"run", "reservation_id":"res", "reserved_units":"1", "expires_at":expires,
                 "broker_state":{"version":14,"hash":"broker-hash-14"}}
        readback={"schema":"foundation.quota-reservation-readback/v1", "state":"RESERVED", **{k:receipt[k] for k in
                  ("resource_id","run_id","reservation_id","reserved_units","expires_at","broker_state")}}
        rp=self.root/"reservation.json"; rb=self.root/"quota-readback.json"
        rp.write_text(json.dumps(receipt)); rb.write_text(json.dumps(readback))
        sig=self.root/"quota-readback.sig"
        subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",str(self.private_key),"-in",str(rb),"-out",str(sig)],check=True,capture_output=True)
        base=dict(state_dir=str(self.root/"state"), reservation_receipt=str(rp), foundation_readback=str(rb),
                  foundation_readback_signature=str(sig), units=1)
        results=[]
        def consume(key):
            try: adapter.quota(argparse.Namespace(**base, operation="consume", idempotency_key=key)); results.append(("ok", key))
            except adapter.ResourceError: results.append(("blocked", key))
        threads=[threading.Thread(target=consume,args=(f"consume-{i}",)) for i in range(2)]
        [x.start() for x in threads]; [x.join() for x in threads]
        self.assertCountEqual([x[0] for x in results],["ok","blocked"])
        successful=next(key for status,key in results if status == "ok")
        q=adapter.quota(argparse.Namespace(**base, operation="consume", idempotency_key=successful))
        self.assertEqual(Decimal(q["consumed_units"]),Decimal("1"))
    def test_local_quota_reserve_without_foundation_proof_fails_closed(self):
        args=argparse.Namespace(state_dir=str(self.root/"state"), reservation_receipt=None, foundation_readback=None,
                                foundation_readback_signature=None, units=0,
                                operation="release", idempotency_key="x")
        with self.assertRaisesRegex(adapter.ResourceError, "FOUNDATION_RESERVATION_PROOF_REQUIRED"): adapter.quota(args)

if __name__ == "__main__": unittest.main()
