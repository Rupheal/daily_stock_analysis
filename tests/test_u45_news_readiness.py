import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('u45news',ROOT/'scripts'/'probe_u45_news_multisource.py')
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class TestU45NewsReadiness(unittest.TestCase):
    def test_dedupe_key_casefolds_title(self):
        a=M.dedupe_key('  ABC   News  ','Wed, 16 Sep 2026 01:00:00 GMT')
        b=M.dedupe_key('abc news','Wed, 16 Sep 2026 01:00:00 GMT')
        self.assertEqual(a,b)

    def test_exact_duplicate_removed(self):
        rows=[
            {'title':'Issuer raises guidance','published':'Wed, 16 Sep 2026 01:00:00 GMT','url':'a'},
            {'title':'issuer raises guidance','published':'Wed, 16 Sep 2026 01:00:00 GMT','url':'b'},
        ]
        out,removed=M.dedupe_recent_relevant(rows)
        self.assertEqual(len(out),1); self.assertEqual(removed,1)

    def test_same_title_different_time_not_forced_duplicate(self):
        rows=[
            {'title':'Issuer update','published':'Wed, 16 Sep 2026 01:00:00 GMT'},
            {'title':'Issuer update','published':'Wed, 16 Sep 2026 02:00:00 GMT'},
        ]
        out,removed=M.dedupe_recent_relevant(rows)
        self.assertEqual(len(out),2); self.assertEqual(removed,0)

    def test_no_retrieval_means_all_closed(self):
        r=M.readiness(False,False)
        self.assertFalse(r['retrieval_ready']); self.assertFalse(r['relevance_ready'])
        self.assertFalse(r['event_ready']); self.assertFalse(r['formal_news_ready'])

    def test_retrieval_only_does_not_promote(self):
        r=M.readiness(True,False)
        self.assertTrue(r['retrieval_ready']); self.assertFalse(r['relevance_ready'])
        self.assertFalse(r['event_ready']); self.assertFalse(r['formal_news_ready'])

    def test_relevance_does_not_promote_event(self):
        r=M.readiness(True,True)
        self.assertTrue(r['retrieval_ready']); self.assertTrue(r['relevance_ready'])
        self.assertFalse(r['event_ready']); self.assertFalse(r['formal_news_ready'])

    def test_formal_gate_is_explicit_fail_closed(self):
        r=M.readiness(True,True)
        self.assertEqual(r['event_gate_status'],'NOT_FORMALLY_CLASSIFIED_FAIL_CLOSED')
        self.assertEqual(r['formal_gate_status'],'NOT_ACCEPTED_FAIL_CLOSED')

    def test_alias_cleaning_preserves_ordinary_name(self):
        self.assertEqual(M.clean_alias('阿里巴巴-W'),'阿里巴巴')
        self.assertEqual(M.clean_alias('腾讯控股'),'腾讯控股')


class TestOfficialAliasFallback(unittest.TestCase):
    def test_unrelated_results_do_not_suppress_official_alias(self):
        from unittest.mock import patch
        from datetime import datetime,timezone
        member={'name':'腾讯控股','official_name':'TENCENT','code':'00700'}
        with patch.object(M,'google_once',return_value={'items_returned':20,'recent_title_issuer_hits':0}) as probe:
            M.fetch_google(member,10,datetime.now(timezone.utc))
        self.assertEqual(probe.call_count,2)

if __name__=='__main__':
    unittest.main(verbosity=2)
