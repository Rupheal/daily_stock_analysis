import copy,unittest
from scripts.build_u45_prep_ledger import reviewed_news_ready
class Tests(unittest.TestCase):
 def good(self):
  return {'target_session':'2026-09-16','source_evidence_sha256':'a'*64,'members':[{'code':'00700','status':'PASS_REVIEWED_COVERAGE','reviewer':'synthetic-review','reviewed_at':'2026-09-17T08:55:00+08:00','limitations_disclosed':True,'company_identity_verified':True,'facts_opinions_separated':True,'deduplicated':True,'sources':[{'url':'https://example.com/synthetic','sha256':'b'*64,'available_at':'2026-09-17T08:00:00+08:00'}]}]}
 def test_reviewed_without_new_event_is_not_automatically_blocked(self):
  self.assertTrue(reviewed_news_ready('00700','2026-09-16',self.good(),'a'*64,'2026-09-17T09:00:00+08:00'))
 def test_wrong_hash_and_future_review_rejected(self):
  d=self.good();self.assertFalse(reviewed_news_ready('00700','2026-09-16',d,'c'*64,'2026-09-17T09:00:00+08:00'));d['members'][0]['reviewed_at']='2026-09-17T09:01:00+08:00';self.assertFalse(reviewed_news_ready('00700','2026-09-16',d,'a'*64,'2026-09-17T09:00:00+08:00'))
 def test_retrieval_only_never_promoted(self):
  d=self.good();d['members'][0]['status']='RSS_PARSED';self.assertFalse(reviewed_news_ready('00700','2026-09-16',d,'a'*64,'2026-09-17T09:00:00+08:00'))
 def test_stale_session_and_missing_source_rejected(self):
  d=self.good();self.assertFalse(reviewed_news_ready('00700','2026-09-15',d,'a'*64,'2026-09-17T09:00:00+08:00'));d['members'][0]['sources']=[];self.assertFalse(reviewed_news_ready('00700','2026-09-16',d,'a'*64,'2026-09-17T09:00:00+08:00'))
if __name__=='__main__':unittest.main()
