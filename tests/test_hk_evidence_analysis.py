import copy
import json
import unittest
from pathlib import Path

from src.services.hk_evidence_analysis import WATCH, validate_judgments, build_evidence_input, render_research_brief
from src.reports.xiaomi_fact_brief import render_html, render_markdown


class BoundedJudgmentTests(unittest.TestCase):
    def setUp(self):
        self.input = {'evidence': [{'id': 'risk:original', 'reason_codes': ['unresolved_claim_requires_followup']}]}
        self.valid = {'view': 'cautious', 'execution_basis': dict(WATCH),
            'condition_ids': ['primary_risk_update'], 'evidence_assessments': [
                {'evidence_id': 'risk:original', 'direction': 'uncertain', 'confidence': 'low', 'reason_code': 'unresolved_claim_requires_followup'}]}

    def test_schema_pass_is_explicitly_not_semantic_or_strategy_approval(self):
        audit = validate_judgments(self.valid, self.input)
        self.assertTrue(audit['schema_passed'])
        self.assertEqual(audit['semantic_review'], 'pending')
        self.assertEqual(audit['strategy_validity'], 'unverified')

    def test_final_consumer_preserves_real_primary_numbers_and_periods(self):
        preflight = json.loads((Path(__file__).parent/'fixtures/xiaomi_primary_preflight_20260912.json').read_text())
        payload = build_evidence_input(preflight, require_fresh=False)
        for evidence in payload['evidence']:
            if evidence['id'].startswith('financial:'):
                self.assertEqual({f['period_end'][5:] for f in evidence['data']}, {'06-30'})
        judgments = copy.deepcopy(self.valid)
        judgments['evidence_assessments'] = [{'evidence_id': e['id'], 'direction': 'uncertain', 'confidence': 'low', 'reason_code': e['reason_codes'][0]} for e in payload['evidence']]
        brief = render_research_brief(preflight,payload,judgments)
        for rendered in (render_html(brief), render_markdown(brief)):
            self.assertIn('9462405', rendered)
            self.assertIn('2050234', rendered)
            self.assertIn('1900000', rendered)
            self.assertNotIn('费用为0', rendered)
            for document in preflight['verified_primary_evidence']['documents']:
                self.assertIn(document['url'], rendered)
        self.assertFalse(brief['trading_plan_enabled'])

    def test_all_real_failed_free_form_reports_are_rejected_without_rewriting(self):
        fixtures = Path(__file__).parent/'fixtures'
        for file in fixtures.glob('xiaomi_model*.json'):
            raw = json.loads(file.read_text())
            original = copy.deepcopy(raw)
            with self.assertRaises(ValueError):
                validate_judgments(raw.get('result', raw), self.input)
            self.assertEqual(raw, original)

    def test_omission_duplicate_fabrication_and_second_prices_fail(self):
        candidates = []
        a = copy.deepcopy(self.valid);a['evidence_assessments']=[];candidates.append(a)
        a = copy.deepcopy(self.valid);a['evidence_assessments']*=2;candidates.append(a)
        a = copy.deepcopy(self.valid);a['evidence_assessments'][0]['evidence_id']='invented';candidates.append(a)
        a = copy.deepcopy(self.valid);a['execution_basis']['stop_price']=25.44;candidates.append(a)
        a = copy.deepcopy(self.valid);a['trend_analysis']='均线全部向下';candidates.append(a)
        a = copy.deepcopy(self.valid);a['evidence_assessments'][0]['assessment']='无重大利空';candidates.append(a)
        for candidate in candidates:
            with self.assertRaises(ValueError):
                validate_judgments(candidate,self.input)


if __name__ == '__main__':
    unittest.main()
