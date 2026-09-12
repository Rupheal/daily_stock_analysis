import unittest
from scripts.run_hk_clock_replay import clock_pairs, valid_price_rows


class ClockReplayTest(unittest.TestCase):
    def test_later_us_close_cannot_enter_hk_morning_or_repeat_after_us_holiday(self):
        sp={'2025-04-02':'100','2025-04-03':'95','2025-04-04':'90','2025-04-07':'200'}
        vix={'2025-04-02':'20','2025-04-03':'25','2025-04-04':'30','2025-04-07':'5'}
        rows=[{'date':'2025-04-07','open':'10','close':'9'},
              {'date':'2025-04-08','open':'9','close':'10'},
              {'date':'2025-04-09','open':'10','close':'11'}]
        pairs,excluded=clock_pairs(rows,sp,vix)
        self.assertEqual([p['us_date'] for p in pairs],['2025-04-04','2025-04-07'])
        self.assertTrue(pairs[0]['sp_down_vix_up'])
        self.assertFalse(pairs[1]['sp_down_vix_up'])
        self.assertEqual(excluded[0]['reason'],'US_observation_already_used')

    def test_real_original_bad_ohlc_is_not_repaired_by_rounding(self):
        data={'symbol':'bad','rows':[{'Date':'2026-09-11','Open':48.58,'High':48.38,'Low':46.94,'Close':47.46,'Volume':1674011}]}
        with self.assertRaises(ValueError):valid_price_rows(data,'bad')
