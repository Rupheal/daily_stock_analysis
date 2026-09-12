import json
from pathlib import Path
import tempfile
import unittest
from src.services.hk_research_replay import (
    parse_hkex_southbound, parse_sse_southbound, parse_fred_csv,
    admits_point_in_time, freeze_observation, append_observation_outcome,
)

FIXTURES = Path(__file__).parent/'fixtures/hk_mechanism_sources'


class ResearchReplayTest(unittest.TestCase):
    def test_real_exchange_amounts_and_channel_scope(self):
        raw = (FIXTURES/'flow-20260911.js').read_text()
        result = parse_hkex_southbound(raw, '2026-09-11')
        self.assertEqual(result['net_buy_hkd_million'], '4431.02')
        self.assertFalse(result['historical_pit_verified'])
        with self.assertRaises(ValueError):
            parse_hkex_southbound(raw, '2025-04-07')
        data = json.loads(raw.split('=',1)[1])
        data = [r for r in data if r['market']!='SZSE Southbound']
        with self.assertRaises(ValueError):
            parse_hkex_southbound(json.dumps(data), '2026-09-11')
        old = parse_sse_southbound((FIXTURES/'sse-flow-20250407.jsonp').read_text(), '2025-04-07')
        self.assertEqual(old['net_buy'], '91.71')
        self.assertIsNone(old['combined_southbound'])

    def test_wrong_currency_series_and_missing_not_filled(self):
        raw = 'observation_date,DGS10\n2025-04-01,4.17\n2025-04-02,.\n'
        self.assertIsNone(parse_fred_csv(raw, 'DGS10')[1]['value'])
        with self.assertRaises(ValueError):
            parse_fred_csv(raw, 'DGS2')

    def test_archive_or_future_availability_not_admitted(self):
        self.assertFalse(admits_point_in_time({'historical_pit_verified': False}, '2025-04-07T01:00:00+00:00'))
        evidence = {'historical_pit_verified':True,'available_at':'2025-04-07T08:00:00+00:00'}
        self.assertFalse(admits_point_in_time(evidence, '2025-04-07T01:00:00+00:00'))
        self.assertTrue(admits_point_in_time(evidence, '2025-04-08T01:00:00+00:00'))

    def test_immutable_original_and_waiting_not_fake_return(self):
        with tempfile.TemporaryDirectory() as directory:
            record = {'rules_sha256':'a'*64,'input_sha256':'b'*64,'available_at':'2026-09-12T16:00:00+00:00','reference_close':'26.36'}
            path = freeze_observation(directory, record)
            with self.assertRaises(FileExistsError):
                freeze_observation(directory, record)
            for horizon in [1,3,5,10,20]:
                result=append_observation_outcome(path,horizon,[],'2026-09-12T16:10:00+00:00','26.36')
                self.assertEqual(result['status'],'waiting')
            path.write_text('{}')
            with self.assertRaises(ValueError):
                append_observation_outcome(path,1,[],'2026-09-12T16:10:00+00:00','26.36')

    def test_actual_session_order_and_frozen_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path=freeze_observation(directory,{'rules_sha256':'a'*64,'input_sha256':'b'*64,'available_at':'2025-04-02T00:00:00+00:00','reference_close':'10'})
            session={'date':'2025-04-03','open_at':'2025-04-03T01:30:00+00:00','close_at':'2025-04-03T08:10:00+00:00','calendar_verified':True,'price_verified':True,'sequence_from_report':2,'close':'11'}
            with self.assertRaises(ValueError):
                append_observation_outcome(path,1,[session],'2025-04-04T00:00:00+00:00','10')
            session['sequence_from_report']=1
            with self.assertRaises(ValueError):
                append_observation_outcome(path,1,[session],'2025-04-04T00:00:00+00:00','9')
            result=append_observation_outcome(path,1,[session],'2025-04-04T00:00:00+00:00','10')
            self.assertEqual(result['reference_return_pct'],'10.0')
            self.assertIsNone(result['strategy_return'])
