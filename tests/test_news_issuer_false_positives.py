import unittest
from scripts.probe_u45_news_multisource import issuer_title_matches

class Tests(unittest.TestCase):
 def test_venue_and_publisher_are_not_hkex_company(self):
  self.assertFalse(issuer_title_matches('Hong Kong Ferry revenue – HKEX:50 - TradingView',['HKEX','香港交易所']))
  self.assertFalse(issuer_title_matches('HKEX Market Search Result - hkex.com.hk',['HKEX']))
  self.assertFalse(issuer_title_matches('Stock Connect statistics - HKEX',['HKEX']))
 def test_issuer_and_ticker_context_are_retained(self):
  self.assertTrue(issuer_title_matches('HKEX announces interim results - News',['HKEX']))
  self.assertTrue(issuer_title_matches('快手－Ｗ回購40萬股 - TradingView',['快手']))
 def test_short_english_alias_must_be_whole_token(self):
  self.assertFalse(issuer_title_matches('Cigarette company results',['CIG']))
  self.assertTrue(issuer_title_matches('CIG reports results',['CIG']))
