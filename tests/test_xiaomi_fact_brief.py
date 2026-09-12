"""Acceptance of the user-facing no-model product, including recorded failures."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

from src.reports.xiaomi_fact_brief import build_fact_brief, render_html, render_markdown
from scripts.run_xiaomi_fact_brief import main

FIXTURES = Path(__file__).parent / 'fixtures'
NOW = '2026-09-12T15:00:00+00:00'


class FactBriefTests(unittest.TestCase):
    def setUp(self):
        self.input = json.loads((FIXTURES/'xiaomi_fact_preflight_20260912.json').read_text())

    def build(self, **kwargs):
        return build_fact_brief(self.input, generated_at=NOW, **kwargs)

    def test_mixed_slopes_and_candle_have_one_recomputable_description(self):
        result = self.build()
        markdown = render_markdown(result)
        self.assertIn('MA20 | 27.35 | 27.39 | 上升 0.04', markdown)
        self.assertIn('MA5 | 27.03 | 26.62 | 下降 0.41', markdown)
        self.assertIn('MA5 < MA10 < MA20', markdown.replace('&lt;', '<'))
        for value in ('0.70 港元', '0.30 港元', '0.22 港元', '57.38%', '+1.70%'):
            self.assertIn(value, markdown)
        self.assertFalse(result['trading_plan_enabled'])
        self.assertEqual(result['model_http_requests'], 0)

    def test_all_recorded_model_failures_cannot_reenter_fact_product(self):
        baseline = self.build()['sections']
        fixtures = list(FIXTURES.glob('xiaomi_model*.json'))
        self.assertGreaterEqual(len(fixtures), 3)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                self.input['raw_response'] = json.loads(fixture.read_text())
                self.input['trend_analysis'] = '均线系统仍发散向下'
                self.input['pattern_analysis'] = '收盘略低于开盘价上方压力区'
                result = self.build()
                self.assertEqual(baseline, result['sections'])
                for output in (render_html(result), render_markdown(result)):
                    self.assertNotIn('均线系统仍发散向下', output)
                    self.assertNotIn('开盘价上方压力区', output)

    def test_zero_range_does_not_invent_a_candle_fraction(self):
        today = self.input['today']
        today.update(open=26.36, high=26.36, low=26.36, close=26.36)
        result = self.build()
        self.assertIsNone(result['facts']['body_fraction_of_range'])
        self.assertIn('无法计算（高低相等）', render_markdown(result))

    def test_red_candle_can_coexist_with_positive_close_to_close_change(self):
        self.input['today'].update(open=26.5)
        text = render_markdown(self.build())
        self.assertIn('阴线（收盘低于开盘）', text)
        self.assertIn('+1.70%', text)

    def test_all_equal_moving_averages_do_not_claim_an_order(self):
        for row in ('today', 'yesterday'):
            self.input[row].update(ma5=27.0, ma10=27.0, ma20=27.0)
        text = render_markdown(self.build())
        self.assertIn('MA10 = MA20 = MA5', text)
        self.assertEqual(text.count('持平 0.00'), 3)

    def test_bullish_and_mixed_order_not_hardcoded_to_xiaomi_fixture(self):
        self.input['today'].update(ma5=28.0, ma10=27.8, ma20=27.5)
        text = render_markdown(self.build()).replace('&lt;', '<')
        self.assertIn('MA20 < MA10 < MA5', text)
        self.assertEqual(text.count('上升'), 3)

    def test_bad_prices_missing_indicators_estimates_and_failed_gate_block(self):
        original = copy.deepcopy(self.input)
        changes = [('high', 20), ('close', float('nan')), ('ma20', None),
                   ('ma5', -1), ('volume', -1), ('volume', 0.5), ('is_estimated', True)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.input = copy.deepcopy(original)
                self.input['today'][field] = value
                with self.assertRaises(ValueError):
                    self.build()
        for field, value in [('passed', False), ('overlap', 59), ('symbol', 'HK00700')]:
            self.input = copy.deepcopy(original)
            self.input[field] = value
            with self.assertRaises(ValueError):
                self.build()

    def test_refresh_requires_correct_complete_session_and_recent_preflight(self):
        with self.assertRaises(ValueError):
            self.build(mode='refresh')
        with self.assertRaises(ValueError):
            self.build(mode='refresh', expected_date='2026-09-14')
        result = self.build(mode='refresh', expected_date='2026-09-11')
        self.assertEqual(result['mode'], 'refresh')
        self.input['prepared_at'] = '2026-09-12T10:00:00+00:00'
        with self.assertRaises(ValueError):
            self.build(mode='refresh', expected_date='2026-09-11')
        self.assertIn('快照回放', render_markdown(self.build()))

    def test_missing_news_and_issuer_disclose_failure_but_keep_valid_prices(self):
        self.input['hk_report_contract']['news_events'] = []
        self.input['issuer_announcements'] = {'items': [], 'status': 'failed', 'error': 'test timeout'}
        self.input['news_count'] = 0
        self.input['origins'] = []
        text = render_markdown(self.build())
        self.assertIn('26.36', text)
        self.assertIn('新闻缺失', text)
        self.assertIn('公告采集失败：test timeout', text)
        self.assertIn('xiaomi-india-sfio-20260909', text)
        self.assertIn('当前是否已立案或已有裁决未知', text)

    def test_old_future_duplicate_and_unlinked_news_are_explicitly_quarantined(self):
        events = self.input['hk_report_contract']['news_events']
        event = events[0]
        events.append(copy.deepcopy(event))
        events[1]['published_at'] = '2026-09-13 01:00:00'
        events[2]['published_at'] = '2026-09-01 01:00:00'
        events[3]['source_urls'] = ['javascript:alert(1)']
        text = render_markdown(self.build())
        self.assertIn('duplicate_event_id', text)
        self.assertIn('outside_72_hour_window', text)
        self.assertIn('Invalid source URL', text)

    def test_html_escapes_external_headlines(self):
        self.input['hk_report_contract']['news_events'][0]['title'] = '<script>alert(1)</script>'
        output = render_html(self.build())
        self.assertNotIn('<script>', output)
        self.assertIn('&lt;script&gt;', output)

    def test_cli_snapshot_runs_with_network_disabled_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory, patch('socket.socket', side_effect=AssertionError('No network')):
            with patch('builtins.print'):
                status = main(['--preflight', str(FIXTURES/'xiaomi_fact_preflight_20260912.json'), '--output-dir', directory])
            self.assertEqual(status, 0)
            roots = list(Path(directory).iterdir())
            self.assertEqual(len(roots), 1)
            self.assertTrue((roots[0]/'xiaomi-facts.html').is_file())
            self.assertTrue((roots[0]/'manifest.json').is_file())

    def test_failed_cli_never_leaves_a_publishable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            self.input['passed'] = False
            source = Path(directory)/'bad.json'
            source.write_text(json.dumps(self.input))
            with patch('builtins.print'):
                status = main(['--preflight', str(source), '--output-dir', str(Path(directory)/'output')])
            self.assertEqual(status, 1)
            self.assertEqual(list(Path(directory).rglob('xiaomi-facts.html')), [])
            self.assertEqual(len(list(Path(directory).rglob('failure.json'))), 1)

    @unittest.skipUnless(importlib.util.find_spec('requests') and (Path(__file__).parents[1]/'data_provider/tencent_fetcher.py').exists(),
                         'Full dependency integration runs in cloud CI')
    def test_source_outage_allows_facts_but_keeps_model_preflight_strict(self):
        import pandas as pd
        import scripts.prepare_xiaomi_acceptance as preparation
        from unittest.mock import MagicMock
        rows = []
        for day in pd.date_range(end='2026-09-11', periods=65):
            row = dict(self.input['today'], date=day.strftime('%Y-%m-%d'))
            if row['date'] == '2026-09-10':
                row.update(self.input['yesterday'])
            rows.append(row)
        frame = pd.DataFrame(rows)
        independent = frame.set_index('date').copy()
        independent.index = pd.DatetimeIndex(independent.index, name='Date')
        fetcher = MagicMock()
        fetcher._calculate_indicators.return_value = frame
        response = MagicMock(url='https://web.ifzq.gtimg.cn/test')
        response.json.return_value = {}
        with ExitStack() as stack, tempfile.TemporaryDirectory() as directory:
            stack.enter_context(patch.object(preparation, 'get_effective_trading_date', return_value='2026-09-11'))
            stack.enter_context(patch.object(preparation.requests, 'get', return_value=response))
            stack.enter_context(patch.object(preparation, '_extract_kline_rows', return_value=rows))
            stack.enter_context(patch.object(preparation, 'TencentFetcher', return_value=fetcher))
            stack.enter_context(patch.object(preparation.yf, 'Ticker', return_value=MagicMock(history=MagicMock(return_value=independent))))
            stack.enter_context(patch.object(preparation, 'IntelligenceService', side_effect=TimeoutError('news timeout')))
            stack.enter_context(patch.object(preparation, 'fetch_issuer_announcements', side_effect=TimeoutError('issuer timeout')))
            stack.enter_context(patch.object(preparation, 'get_db'))
            stack.enter_context(patch('builtins.print'))
            result = preparation.prepare(Path(directory)/'facts', allow_partial_news=True)
            self.assertEqual(result['overlap'], 65)  # Real compare_prices still executes.
            self.assertEqual(result['component_status']['news'], 'unavailable')
            self.assertEqual(result['component_status']['issuer'], 'failed')
            text = render_markdown(build_fact_brief(result))
            self.assertIn('news timeout', text)
            self.assertIn('issuer timeout', text)
            with self.assertRaisesRegex(TimeoutError, 'news timeout'):
                preparation.prepare(Path(directory)/'strict')


if __name__ == '__main__':
    unittest.main()
