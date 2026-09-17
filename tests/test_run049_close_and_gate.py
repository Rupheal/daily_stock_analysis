import copy
import unittest

from run049_close_and_gate import TARGET, build_o52_audit, build_u_gate, build_u_refresh, coverage_map


def universe45():
    return {"member_count":45,"members":[{"code":f"{i:05d}","official_name":f"N{i}","english_name":f"E{i}"} for i in range(1,46)]}


def coverage(n, target=TARGET):
    return {
        "expected_complete_session":target,
        "coverage_denominator":n,
        "coverage":[{"code":"hk"+f"{i:05d}","status":"current_valid_bar","latest_date":target,
                     "latest_ohlcv":[10.0,11.0,9.5,10.5,1000.0],"native_log_mentions_code":True}
                    for i in range(1,n+1)]
    }


def prior52():
    return {"O_denominator":660,"isolated":52,"checks":[
        {"code":f"{i:05d}","status":"ISOLATED","reason":"THIRD_SOURCE_CONFLICT_REMAINS"} for i in range(1,53)
    ]}


class TestRun049(unittest.TestCase):
    def test_u_denominator_and_target(self):
        out=build_u_refresh(universe45(),coverage(45))
        self.assertEqual(out["denominator"],45)
        self.assertEqual(out["current_valid_count"],45)
        self.assertEqual(out["target_session"],TARGET)
        self.assertEqual(out["facts"][0]["close"],10.5)

    def test_stale_916_cannot_satisfy_917(self):
        with self.assertRaisesRegex(ValueError,"STALE_OR_WRONG_TARGET_SESSION"):
            build_u_refresh(universe45(),coverage(45,"2026-09-16"))

    def test_duplicate_coverage_fails_closed(self):
        c=coverage(45); c["coverage"][-1]["code"]=c["coverage"][0]["code"]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_COVERAGE_CODE"):
            coverage_map(c,TARGET,45)

    def test_u_gate_never_invents_rank_macro_or_buy_zone(self):
        refresh=build_u_refresh(universe45(),coverage(45))
        gate=build_u_gate(refresh,{"prerequisites":["accepted_U_BUY_and_rank","verified_macro_cap"]},{})
        self.assertEqual(gate["formal_signal_gate"],"NO_GO")
        self.assertFalse(gate["ranking"]["executed"])
        self.assertEqual(gate["ranking"]["Top3"],[])
        self.assertIsNone(gate["macro_cap"]["accepted_value"])
        self.assertEqual(gate["buy_zone"]["accepted_members"],0)

    def test_o52_current_bar_does_not_release_historical_isolation(self):
        out=build_o52_audit(prior52(),coverage(660))
        self.assertEqual(out["reviewed_prior_isolations"],52)
        self.assertEqual(out["current_session_data_ready_within_o52"],52)
        self.assertEqual(out["historical_source_conflicts_resolved_this_run"],0)
        self.assertEqual(out["released_to_original_ranking_chain_this_run"],0)
        self.assertTrue(all(not r["historical_source_conflict_resolved"] for r in out["rows"]))

    def test_missing_current_o_bar_preserves_denominator(self):
        c=coverage(660); c["coverage"][0]["status"]="invalid_or_stale"; c["coverage"][0]["latest_date"]="2026-09-16"
        out=build_o52_audit(prior52(),c)
        self.assertEqual(out["reviewed_prior_isolations"],52)
        self.assertEqual(out["current_session_data_ready_within_o52"],51)
        self.assertEqual(out["current_session_still_not_ready_within_o52"],1)

    def test_prior_not_52_fails_closed(self):
        p=prior52(); p["isolated"]=51
        with self.assertRaisesRegex(ValueError,"RUN045_O52_BASELINE_MISMATCH"):
            build_o52_audit(p,coverage(660))


if __name__=="__main__":
    unittest.main()
