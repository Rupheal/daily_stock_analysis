from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import unittest

from scripts.hk_batch_integrity import compare_history, validate_native_context, tencent_rows


class FundedBatchInputTest(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(date=str(date(2026, 8, 20)+timedelta(days=i)), open=20+i, high=22+i,
                         low=19+i, close=21+i, volume=100000, data_source='YfinanceFetcher') for i in range(21)]
        self.target = self.rows[-1]['date']

    def test_independent_disagreement_isolated_without_mutating_native(self):
        other = deepcopy(self.rows); other[-1]['volume'] += 1
        before = deepcopy(self.rows)
        result = compare_history(self.rows, other, self.target)
        self.assertFalse(result['passed'])
        self.assertEqual(result['mismatches'][0]['field'], 'volume')
        self.assertEqual(self.rows, before)
        other = deepcopy(self.rows); other[-1]['open'] = other[-1]['high'] + .01
        with self.assertRaisesRegex(ValueError, 'geometry'): compare_history(self.rows, other, self.target)

    def test_same_provider_and_missing_session_cannot_pass(self):
        same = deepcopy(self.rows); same[-1]['data_source'] = 'TencentFetcher'
        with self.assertRaisesRegex(ValueError, 'not_independent'): compare_history(same, self.rows, self.target)
        with self.assertRaises(ValueError): compare_history(self.rows, self.rows[:-1], self.target)

    def test_context_mean_and_symbol_price_remain_tied_to_verified_rows(self):
        today = deepcopy(self.rows[-1])
        for n in (5, 10, 20): today['ma'+str(n)] = float(sum(Decimal(str(r['close'])) for r in self.rows[-n:])/n)
        context = {'today': today, 'yesterday': self.rows[-2]}
        self.assertTrue(validate_native_context(context, self.rows))
        context['today']['ma20'] += .02
        with self.assertRaisesRegex(ValueError, 'mean'): validate_native_context(context, self.rows)

    def test_tencent_hk_volume_is_shares_and_adjustment_disclosed(self):
        raw = {'data': {'hk01810': {'day': [['2026-09-11', '25.66', '26.36', '26.66', '25.44', '113533443']]}}}
        rows, adjustment = tencent_rows(raw, 'HK01810')
        self.assertEqual(adjustment, 'day')
        self.assertEqual(rows[0]['volume'], '113533443')
        self.assertEqual(rows[0]['high'], '26.66')

    def test_upgraded_tencent_data_requires_a_different_provider(self):
        tencent = deepcopy(self.rows)
        for row in tencent: row['data_source'] = 'TencentFetcher'
        self.assertTrue(compare_history(tencent, self.rows, self.target, 'YfinanceFetcher')['passed'])
        with self.assertRaisesRegex(ValueError, 'not_independent'):
            compare_history(tencent, self.rows, self.target, 'TencentFetcher')
