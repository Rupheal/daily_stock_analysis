import copy
import hashlib
import json
import unittest
from pathlib import Path

from src.services.xiaomi_primary_evidence import REGISTRY, derived_metrics, verify_pages, verify_pdf


class PrimaryEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY.read_text())
        cls.fixture = json.loads((Path(__file__).parent/'fixtures/xiaomi_primary_pages_20260912.json').read_text())

    def test_real_disclosure_rows_match_reviewed_period_columns(self):
        for document in self.registry['documents']:
            evidence = self.fixture[document['id']]
            self.assertEqual(evidence['sha256'], document['sha256'])
            verify_pages(document, evidence['pages'])

    def test_swapped_quarter_and_half_year_rejected(self):
        doc = copy.deepcopy(self.registry['documents'][0])
        doc['tables'][0]['values'][0], doc['tables'][0]['values'][2] = doc['tables'][0]['values'][2], doc['tables'][0]['values'][0]
        with self.assertRaisesRegex(ValueError, 'column mismatch'):
            verify_pages(doc, self.fixture[doc['id']]['pages'])

    def test_quarter_profit_and_cashflow_not_filled_from_half_year(self):
        doc = self.registry['documents'][0]
        fields = verify_pages(doc, self.fixture[doc['id']]['pages'])
        ocf = [f for f in fields if f['metric'] == 'operating_cash_flow']
        self.assertEqual({f['period_kind'] for f in ocf}, {'half_year'})
        parent = next(f for f in fields if f['id'] == 'net_profit_parent:2026-04-01:2026-06-30')
        self.assertEqual(parent['amount_cny'], '9462405000')
        metrics = derived_metrics(fields)
        revenue_yoy = next(m for m in metrics if m['id'] == 'revenue:2026-04-01:2026-06-30:yoy_pct')
        self.assertAlmostEqual(float(revenue_yoy['value']), -6.0665, places=3)

    def test_cumulative_buyback_cannot_replace_daily(self):
        doc = copy.deepcopy(self.registry['documents'][-1])
        doc['buyback']['shares'] = 116593200
        with self.assertRaisesRegex(ValueError, 'Daily buyback differs'):
            verify_pages(doc, self.fixture[doc['id']]['pages'])

    def test_changed_pdf_bytes_fail_before_parsing(self):
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            verify_pdf(self.registry['documents'][0], b'%PDF-changed')

    def test_half_year_statement_cannot_close_later_risk(self):
        doc = self.registry['documents'][0]
        self.assertEqual(doc['statements'][0]['scope_end'], '2026-06-30')
        self.assertNotIn('resolution_source', doc)


if __name__ == '__main__':
    unittest.main()
