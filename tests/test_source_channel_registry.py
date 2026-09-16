import unittest

from src.services.source_channel_registry import (
    get_market_channel,
    get_news_channel,
    hk_realtime_catalog_fallback,
    load_source_channel_catalog,
    news_channel_for_url,
    ordered_news_transport_ids,
    resolve_market_priority,
    source_channel_governance,
    source_channel_summary,
)


class SourceChannelRegistryTests(unittest.TestCase):
    def test_catalog_loads_and_has_both_channel_families(self):
        payload = load_source_channel_catalog()
        self.assertEqual(payload["catalog_id"], "dsa-source-channels")
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertGreaterEqual(len(payload["news_channels"]), 25)
        self.assertGreaterEqual(len(payload["market_channels"]), 10)

    def test_news_transport_order_matches_existing_runtime_chain(self):
        self.assertEqual(
            ordered_news_transport_ids(),
            ["anspire", "bocha", "tavily", "brave", "serpapi", "minimax", "searxng"],
        )
        self.assertEqual(
            ordered_news_transport_ids({"brave", "bocha", "searxng"}),
            ["bocha", "brave", "searxng"],
        )

    def test_primary_and_aggregator_evidence_semantics_are_distinct(self):
        hkex = get_news_channel("hkexnews")
        futu = get_news_channel("futu_public_news")
        self.assertEqual(hkex["tier"], "N0_PRIMARY")
        self.assertNotEqual(hkex["single_source_fact_scope"], "none")
        self.assertEqual(futu["tier"], "N3_AGGREGATOR")
        self.assertEqual(futu["single_source_fact_scope"], "none")
        governance = source_channel_governance()
        self.assertFalse(governance["news"]["aggregator_is_independent_confirmation"])
        self.assertFalse(governance["news"]["search_transport_is_evidence"])

    def test_news_url_classifier_uses_publisher_domain(self):
        self.assertEqual(
            news_channel_for_url("https://www.reuters.com/world/example")["id"],
            "reuters",
        )
        self.assertEqual(
            news_channel_for_url("https://www1.hkexnews.hk/listedco/example.pdf")["id"],
            "hkexnews",
        )
        self.assertEqual(
            news_channel_for_url("https://news.futunn.com/post/123")["id"],
            "futu_public_news",
        )
        self.assertIsNone(news_channel_for_url("https://unknown.invalid/story"))

    def test_market_catalog_preserves_explicit_runtime_priority(self):
        self.assertEqual(
            resolve_market_priority("tushare,efinance,akshare_em", market="cn"),
            ["tushare", "efinance", "akshare_em"],
        )
        self.assertEqual(
            resolve_market_priority("futu,longbridge,akshare,yfinance", market="hk"),
            ["futu", "longbridge", "akshare", "yfinance"],
        )

    def test_hk_catalog_fallback_and_market_metadata(self):
        self.assertEqual(
            hk_realtime_catalog_fallback(),
            ["futu", "longbridge", "akshare_em", "yfinance"],
        )
        futu = get_market_channel("futu")
        yfinance = get_market_channel("yfinance")
        self.assertEqual(futu["status"], "integrated_if_configured")
        self.assertEqual(futu["latency_class"], "entitlement_dependent")
        self.assertEqual(yfinance["tier"], "M2_GLOBAL_BACKUP")

    def test_shadow_price_time_rules_are_fail_closed(self):
        governance = source_channel_governance()["market"]
        self.assertTrue(governance["retrieved_at_is_not_price_time"])
        self.assertTrue(governance["reject_future_price_for_shadow_entry"])
        self.assertTrue(governance["never_invent_quote"])

    def test_summary_reports_nonzero_integrated_coverage(self):
        summary = source_channel_summary()
        self.assertGreaterEqual(summary["news_channels"], 25)
        self.assertGreaterEqual(summary["market_channels"], 10)
        self.assertGreater(summary["news_integrated_or_conditional"], 0)
        self.assertGreater(summary["market_integrated_or_conditional"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
