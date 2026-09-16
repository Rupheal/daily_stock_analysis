import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('capital', Path(__file__).parents[1]/'scripts/collect_hk_capital_evidence.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
FIX = Path(__file__).parent/'fixtures/hk_capital'
HKEX = (FIX/'hkex_20260915.js').read_bytes()
HKMA = (FIX/'hkma_20260915.json').read_bytes()


class EvidenceTests(unittest.TestCase):
    def test_real_units_and_two_channel_aggregation(self):
        data = c.parse_hkex(HKEX, '2026-09-15')
        self.assertEqual(c.number(data['net_buy_hkd']), 880670000)
        self.assertEqual(c.number(data['top10_union']['00700']['net_buy_hkd']), -1000054496)

    def test_one_channel_is_not_complete_or_zero(self):
        row = c.parse_hkex(HKEX, '2026-09-15')['top10_union']['01810']
        self.assertEqual(row['status'], 'PARTIAL_CHANNEL_COVERAGE')
        self.assertIsNone(row['net_buy_hkd'])

    def test_wrong_date_rejected(self):
        with self.assertRaisesRegex(ValueError, 'WRONG_DATE'):
            c.parse_hkex(HKEX, '2026-09-16')

    def test_arithmetic_conflict_rejected(self):
        with self.assertRaisesRegex(ValueError, 'TURNOVER_CONFLICT'):
            c.parse_hkex(HKEX.replace(b'47,485.14', b'47,485.19'), '2026-09-15')

    def test_hkma_is_dated_proxy(self):
        row = c.parse_hkma(HKMA, '2026-09-15')
        self.assertEqual(row['fields']['hibor_fixing_1m']['value'], '2.91256')
        self.assertEqual(row['evidence_class'], 'LIQUIDITY_PROXY_NOT_EQUITY_FLOW')
        with self.assertRaises(ValueError):
            c.parse_hkma(HKMA, '2026-09-16')

    def test_nonfinite_and_timezone_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.assertRaises(ValueError):
                c.number(value)
        with self.assertRaises(ValueError):
            c.clock('2026-09-16T09:00:00')

    def test_cutoff_cache_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)/'run'
            with patch.object(c, 'fetch', side_effect=lambda url: (HKEX if 'hkex' in url else HKMA, 1)) as fetch:
                result = c.run('2026-09-15', '2026-09-15T09:00:00+08:00', directory)
                self.assertEqual(result['verified_sources'], 2)
                self.assertEqual(result['cutoff_eligible_sources'], 0)
                self.assertEqual(c.run('2026-09-15', result['cutoff'], directory), result)
                self.assertEqual(fetch.call_count, 2)
                (directory/result['sources'][0]['artifact']).write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'CACHE_HASH_MISMATCH'):
                    c.run('2026-09-15', result['cutoff'], directory)

    def test_source_failure_does_not_abort_other_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fetch(url):
                if 'hkex' in url:
                    raise TimeoutError()
                return HKMA, 1
            with patch.object(c, 'fetch', side_effect=fetch):
                result = c.run('2026-09-15', '2026-09-15T09:00:00+08:00', Path(tmp)/'run')
                self.assertEqual(result['verified_sources'], 1)
                self.assertEqual(result['source_denominator'], 2)
                self.assertEqual(result['sources'][0]['reason'], 'TimeoutError')


if __name__ == '__main__':
    unittest.main()
