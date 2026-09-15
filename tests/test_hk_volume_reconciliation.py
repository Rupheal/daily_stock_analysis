from __future__ import annotations

import math
import unittest

from src.services.hk_volume_reconciliation import (
    LATEST_SESSION_MAX_RELATIVE_DEVIATION,
    PriceVolumeReconciliationError,
    reconcile_volume_pairs,
    validate_latest_session,
    validate_ohlc_pairs,
)

TARGET = '2026-09-15'


def exact_pairs(n=125):
    rows = []
    for i in range(n - 1):
        rows.append((f'2026-05-{(i % 28) + 1:02d}', 1_000_000 + i, 1_000_000 + i))
    rows.append((TARGET, 2_000_000, 2_000_000))
    return rows


class HKVolumeReconciliationTest(unittest.TestCase):
    def test_125_of_125_exact_pass(self):
        result = reconcile_volume_pairs(exact_pairs(), TARGET, unit_semantics_verified=True)
        self.assertEqual(result['latest_session_status'], 'exact')
        self.assertEqual(result['exact_sessions_total'], 125)

    def test_100x_unit_pattern_fails(self):
        rows = exact_pairs()
        rows[10] = (rows[10][0], 100_000_000, 1_000_000)
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'HISTORICAL_NOT_EXACT'):
            reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)

    def test_0_01x_unit_pattern_fails(self):
        rows = exact_pairs()
        rows[10] = (rows[10][0], 10_000, 1_000_000)
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'HISTORICAL_NOT_EXACT'):
            reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)

    def test_latest_small_revision_inside_calibrated_bound_passes(self):
        rows = exact_pairs()
        yahoo = 2_000_000.0
        tencent = yahoo * (1.0 - LATEST_SESSION_MAX_RELATIVE_DEVIATION / 2.0)
        rows[-1] = (TARGET, tencent, yahoo)
        result = reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)
        self.assertEqual(result['latest_session_status'], 'bounded_provider_reconciliation')
        self.assertLessEqual(result['latest_session_relative_deviation'], LATEST_SESSION_MAX_RELATIVE_DEVIATION)

    def test_historical_any_mismatch_fails(self):
        rows = exact_pairs()
        rows[50] = (rows[50][0], rows[50][1] + 1, rows[50][2])
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'HISTORICAL_NOT_EXACT'):
            reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)

    def test_latest_over_calibrated_bound_fails(self):
        rows = exact_pairs()
        yahoo = 2_000_000.0
        rows[-1] = (TARGET, yahoo * (1.0 + LATEST_SESSION_MAX_RELATIVE_DEVIATION + 0.000001), yahoo)
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'LATEST_OUTSIDE_CALIBRATED_BOUND'):
            reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)

    def test_ohlc_mismatch_fails_even_if_volume_would_pass(self):
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'PRICE_DISAGREEMENT_CLOSE'):
            validate_ohlc_pairs([('close', 40.0101, 40.0)])

    def test_unisolated_corporate_action_fails(self):
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'CORPORATE_ACTION_NOT_ISOLATED'):
            reconcile_volume_pairs(exact_pairs(), TARGET, corporate_action_dates={TARGET}, unit_semantics_verified=True)

    def test_nonfinite_volume_fails(self):
        rows = exact_pairs()
        rows[-1] = (TARGET, math.nan, 2_000_000)
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'VOLUME_NONFINITE'):
            reconcile_volume_pairs(rows, TARGET, unit_semantics_verified=True)

    def test_stale_provider_fails(self):
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'PROVIDER_STALE_OR_WRONG_SESSION'):
            validate_latest_session('2026-09-15', '2026-09-14', TARGET)

    def test_unknown_unit_semantics_fails(self):
        with self.assertRaisesRegex(PriceVolumeReconciliationError, 'UNIT_SEMANTICS_UNVERIFIED'):
            reconcile_volume_pairs(exact_pairs(), TARGET)

    def test_ohlc_within_existing_absolute_tolerance_passes(self):
        validate_ohlc_pairs([
            ('open', 40.0000, 40.000002),
            ('high', 41.0000, 41.000002),
            ('low', 39.0000, 39.000002),
            ('close', 40.5000, 40.500002),
        ])


if __name__ == '__main__':
    unittest.main()
