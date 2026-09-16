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


def test_catalog_loads_and_has_both_channel_families():
    payload = load_source_channel_catalog()
    assert payload["catalog_id"] == "dsa-source-channels"
    assert payload["schema_version"] == "1.0"
    assert len(payload["news_channels"]) >= 25
    assert len(payload["market_channels"]) >= 10


def test_news_transport_order_matches_existing_runtime_chain():
    assert ordered_news_transport_ids() == [
        "anspire",
        "bocha",
        "tavily",
        "brave",
        "serpapi",
        "minimax",
        "searxng",
    ]
    assert ordered_news_transport_ids({"brave", "bocha", "searxng"}) == [
        "bocha",
        "brave",
        "searxng",
    ]


def test_primary_and_aggregator_evidence_semantics_are_distinct():
    hkex = get_news_channel("hkexnews")
    futu = get_news_channel("futu_public_news")
    assert hkex["tier"] == "N0_PRIMARY"
    assert hkex["single_source_fact_scope"] != "none"
    assert futu["tier"] == "N3_AGGREGATOR"
    assert futu["single_source_fact_scope"] == "none"
    governance = source_channel_governance()
    assert governance["news"]["aggregator_is_independent_confirmation"] is False
    assert governance["news"]["search_transport_is_evidence"] is False


def test_news_url_classifier_uses_publisher_domain():
    assert news_channel_for_url("https://www.reuters.com/world/example")["id"] == "reuters"
    assert news_channel_for_url("https://www1.hkexnews.hk/listedco/example.pdf")["id"] == "hkexnews"
    assert news_channel_for_url("https://news.futunn.com/post/123")["id"] == "futu_public_news"
    assert news_channel_for_url("https://unknown.invalid/story") is None


def test_market_catalog_preserves_explicit_runtime_priority():
    assert resolve_market_priority("tushare,efinance,akshare_em", market="cn") == [
        "tushare",
        "efinance",
        "akshare_em",
    ]
    assert resolve_market_priority("futu,longbridge,akshare,yfinance", market="hk") == [
        "futu",
        "longbridge",
        "akshare",
        "yfinance",
    ]


def test_hk_catalog_fallback_and_market_metadata():
    assert hk_realtime_catalog_fallback() == ["futu", "longbridge", "akshare_em", "yfinance"]
    futu = get_market_channel("futu")
    yfinance = get_market_channel("yfinance")
    assert futu["status"] == "integrated_if_configured"
    assert futu["latency_class"] == "entitlement_dependent"
    assert yfinance["tier"] == "M2_GLOBAL_BACKUP"


def test_shadow_price_time_rules_are_fail_closed():
    governance = source_channel_governance()["market"]
    assert governance["retrieved_at_is_not_price_time"] is True
    assert governance["reject_future_price_for_shadow_entry"] is True
    assert governance["never_invent_quote"] is True


def test_summary_reports_nonzero_integrated_coverage():
    summary = source_channel_summary()
    assert summary["news_channels"] >= 25
    assert summary["market_channels"] >= 10
    assert summary["news_integrated_or_conditional"] > 0
    assert summary["market_integrated_or_conditional"] > 0
