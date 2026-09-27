import importlib.util, unittest
from datetime import datetime, timezone
from pathlib import Path

BUS=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
pg=load("pg",BUS/"artifact_persistence_gate.py")
sup=load("sup_persist",BUS/"tri_task_supervisor_v03.py")
I="a"*40; O="b"*40; T="c"*40; P="d"*64

def direct_expected():
    return {"mode":"DIRECT_COMMIT","repository":"R/x","branch":"codex/x","input_head":I,"worker_output_head":O,"pr_number":47,"tree_sha":T}
def direct_observed():
    return {"source":"GITHUB_REMOTE_READBACK","repository":"R/x","branch":"codex/x","commit_exists":True,"branch_head":O,"commit_sha":O,"pr_number":47,"pr_head":O,"tree_sha":T,"ancestry_contains_input":True}
def patch_expected():
    return {"mode":"PATCH_RECONSTRUCTION","repository":"R/x","branch":"repair/x","input_head":I,"pr_number":47,"patch_sha256":P,
            "changed_paths":["a.py","b.json"],"target_blobs":{"a.py":"1"*40,"b.json":"2"*40}}
def patch_observed():
    return {"source":"GITHUB_REMOTE_READBACK","repository":"R/x","branch":"repair/x","commit_exists":True,"branch_head":O,"commit_sha":O,
            "pr_number":47,"pr_head":O,"ancestry_contains_input":True,"patch_sha256":P,
            "remote_blobs":{"a.py":"1"*40,"b.json":"2"*40}}

class PersistenceGateTests(unittest.TestCase):
    def test_01_direct_exact_remote_passes(self): self.assertEqual(pg.VERIFIED,pg.evaluate(direct_expected(),direct_observed())["state"])
    def test_02_missing_remote_commit_fails(self):
        o=direct_observed();o["commit_exists"]=False;self.assertRaisesRegex(pg.PersistenceError,"REMOTE_COMMIT_MISSING",pg.evaluate,direct_expected(),o)
    def test_03_branch_head_mismatch_fails(self):
        o=direct_observed();o["branch_head"]="e"*40;self.assertRaisesRegex(pg.PersistenceError,"REMOTE_BRANCH_COMMIT_MISMATCH",pg.evaluate,direct_expected(),o)
    def test_04_worker_output_not_remote_fails(self):
        o=direct_observed();o["branch_head"]=o["commit_sha"]="e"*40;o["pr_head"]="e"*40;self.assertRaisesRegex(pg.PersistenceError,"WORKER_OUTPUT_NOT_REMOTE_HEAD",pg.evaluate,direct_expected(),o)
    def test_05_pr_head_mismatch_fails(self):
        o=direct_observed();o["pr_head"]="e"*40;self.assertRaisesRegex(pg.PersistenceError,"REMOTE_PR_HEAD_MISMATCH",pg.evaluate,direct_expected(),o)
    def test_06_ancestry_required(self):
        o=direct_observed();o["ancestry_contains_input"]=False;self.assertRaisesRegex(pg.PersistenceError,"INPUT_HEAD_NOT_IN_REMOTE_ANCESTRY",pg.evaluate,direct_expected(),o)
    def test_07_tree_pin_required_when_declared(self):
        o=direct_observed();o["tree_sha"]="e"*40;self.assertRaisesRegex(pg.PersistenceError,"REMOTE_TREE_MISMATCH",pg.evaluate,direct_expected(),o)
    def test_08_patch_reconstruction_exact_blobs_passes(self): self.assertEqual(pg.VERIFIED,pg.evaluate(patch_expected(),patch_observed())["state"])
    def test_09_patch_path_set_mismatch_fails(self):
        o=patch_observed();o["remote_blobs"].pop("b.json");self.assertRaisesRegex(pg.PersistenceError,"REMOTE_CHANGED_PATH_SET_MISMATCH",pg.evaluate,patch_expected(),o)
    def test_10_patch_blob_mismatch_fails(self):
        o=patch_observed();o["remote_blobs"]["a.py"]="9"*40;self.assertRaisesRegex(pg.PersistenceError,"REMOTE_TARGET_BLOB_MISMATCH",pg.evaluate,patch_expected(),o)
    def test_11_make_pr_metadata_cannot_substitute_for_remote(self):
        o=direct_observed();o["commit_exists"]=False;o["make_pr_updated"]=True;self.assertRaises(pg.PersistenceError,pg.evaluate,direct_expected(),o)
    def test_12_pending_not_acceptable(self):
        self.assertRaisesRegex(pg.PersistenceError,"REMOTE_PERSISTENCE_NOT_VERIFIED",pg.require_verified,pg.pending(direct_expected(),"LOCAL_ONLY"))
    def test_13_supervisor_rejects_acceptance_without_remote_persistence(self):
        r={"state":"WAIT_DEPENDENCY","updated_at":"2026-09-27T00:00:00Z","lease":{},"last_external_receipt":None}
        self.assertRaisesRegex(ValueError,"REMOTE_PERSISTENCE_NOT_VERIFIED",sup.independent_accept,r,"CONTROL_ROOM","receipt","e"*64,pg.pending(direct_expected(),"LOCAL_ONLY"),datetime.now(timezone.utc))
    def test_14_supervisor_accepts_only_verified_remote(self):
        r={"state":"WAIT_DEPENDENCY","updated_at":"2026-09-27T00:00:00Z","lease":{},"last_external_receipt":None}
        p=pg.evaluate(direct_expected(),direct_observed());sup.independent_accept(r,"CONTROL_ROOM","receipt","e"*64,p,datetime.now(timezone.utc))
        self.assertEqual("ACCEPTED",r["state"]);self.assertEqual(pg.VERIFIED,r["persistence"]["state"])

if __name__=="__main__": unittest.main()
