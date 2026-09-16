import importlib.util
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('evt',ROOT/'scripts'/'classify_u45_news_event_candidates.py')
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


class TestEventCandidates(unittest.TestCase):
    def test_financing_candidate(self):
        c=M.classify_title('壁仞科技据报考虑再配股筹10亿美元')
        self.assertTrue(any(x['category']=='FINANCING_EQUITY' and x['material_candidate'] for x in c))

    def test_clinical_candidate(self):
        c=M.classify_title('康方生物依沃西试验生存期超过竞品')
        self.assertTrue(any(x['category']=='CLINICAL_TRIAL' and x['material_candidate'] for x in c))

    def test_market_commentary_not_material(self):
        c=M.classify_title('港股收市：阿里巴巴逆市升1%')
        self.assertTrue(any(x['category']=='MARKET_PRICE_COMMENTARY' for x in c))
        self.assertFalse(any(x['material_candidate'] for x in c))

    def test_rating_not_material(self):
        c=M.classify_title('高盛维持MINIMAX买入评级')
        self.assertTrue(any(x['category']=='ANALYST_RATING' for x in c))
        self.assertFalse(any(x['material_candidate'] for x in c))

    def test_routine_disclosure_not_material(self):
        c=M.classify_title('中芯国际港股公告：翌日披露报表')
        self.assertTrue(any(x['category']=='ROUTINE_REGULATORY_DISCLOSURE' for x in c))
        self.assertFalse(any(x['material_candidate'] for x in c))

    def test_non_relevant_rows_are_not_classified(self):
        d={'schema_version':'U45_NEWS_MULTISOURCE_v1_2','universe_denominator':45,'execution_eligible_denominator':44,'members_retrieval_ready':44,'members_relevance_ready':0,
           'rows':[{'code':'00001','name':'X','relevance_ready':False,'unique_recent_relevant_items':[{'title':'配股集资','published':'x'}]}]}
        out=M.classify_receipt(d)
        self.assertEqual(out['rows'],[]); self.assertEqual(out['event_candidate_members'],0)

    def test_candidate_does_not_promote_event_ready(self):
        d={'schema_version':'U45_NEWS_MULTISOURCE_v1_2','universe_denominator':45,'execution_eligible_denominator':44,'members_retrieval_ready':44,'members_relevance_ready':1,
           'rows':[{'code':'06082','name':'壁仞科技','relevance_ready':True,'unique_recent_relevant_items':[{'title':'壁仞科技考虑再配股集资','published':'x','url':'u'}]}]}
        out=M.classify_receipt(d)
        self.assertEqual(out['event_candidate_members'],1); self.assertEqual(out['event_ready'],0); self.assertEqual(out['formal_news_ready'],0); self.assertEqual(out['formal_u_acceptance_added'],0)

    def test_resources_remain_zero(self):
        out=M.classify_receipt({'rows':[]})
        self.assertEqual(out['model_http_requests'],0); self.assertEqual(out['paid_data_calls'],0)


if __name__=='__main__': unittest.main(verbosity=2)
