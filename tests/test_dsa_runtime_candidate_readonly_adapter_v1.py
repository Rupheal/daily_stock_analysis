import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from dsa_runtime_candidate_readonly_adapter_v1 import canonical_hash,validate_authority_pair,latest_active_signal


class AdapterTests(unittest.TestCase):
    def fixture(self):
        config={"accounts":{"O":"300000","U":"300000"}}
        ch=canonical_hash(config)
        cmds=[]
        parent=ch
        for account in ("O","U"):
            cmd={"id":f"DSA-CLOSE-20260918-{account}:SIGNAL","account":account,
                 "at":"2026-09-18T16:33:00+08:00","kind":"SIGNAL",
                 "signal":{"id":f"DSA-CLOSE-20260918-{account}","cutoff":"2026-09-18T16:30:00+08:00",
                           "passed":False,"reason":"WAIT"}}
            h=canonical_hash({"parent":parent,"command":cmd})
            cmds.append({"parent":parent,"command":cmd,"hash":h});parent=h
        j={"config":config,"config_hash":ch,"commands":cmds}
        s={"journal_hash":canonical_hash(j)}
        return j,s

    def test_authority_pair_chain_passes(self):
        j,s=self.fixture();r=validate_authority_pair(j,s)
        self.assertTrue(r["summary_matches_journal"])
        self.assertEqual(r["command_count"],2)
        self.assertEqual(r["commands_by_account"],{"O":1,"U":1})

    def test_summary_drift_fails(self):
        j,s=self.fixture();s["journal_hash"]="0"*64
        with self.assertRaisesRegex(ValueError,"ACTIVE_SUMMARY_JOURNAL_HASH_MISMATCH"):
            validate_authority_pair(j,s)

    def test_parent_drift_fails(self):
        j,s=self.fixture();j["commands"][1]["parent"]="bad"
        with self.assertRaisesRegex(ValueError,"ACTIVE_PARENT_CHAIN_MISMATCH"):
            validate_authority_pair(j,s)

    def test_latest_signal_is_no_buy(self):
        j,_=self.fixture();x=latest_active_signal(j,"O","2026-09-18")
        self.assertEqual(x["semantic_action"],"NO_BUY")
        self.assertFalse(x["passed"])

    def test_wrong_session_fails(self):
        j,_=self.fixture()
        with self.assertRaisesRegex(ValueError,"TARGET_SIGNAL_MISSING"):
            latest_active_signal(j,"U","2026-09-17")


if __name__=="__main__":
    unittest.main()
