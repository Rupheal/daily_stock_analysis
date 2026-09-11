import copy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.pipeline import StockAnalysisPipeline
from src.analyzer import GeminiAnalyzer
from src.services.market_data_integrity import (
    MarketDataIntegrityError, validate_daily_context,
)


def context():
    return {"code": "HK01810", "date": "2026-09-10",
            "today": {"date": "2026-09-10", "open": 26.3,
                      "high": 26.4, "low": 25.8, "close": 25.92},
            "yesterday": {"date": "2026-09-09", "close": 26.38}}


def test_missing_session_blocks_instead_of_relabelling():
    with pytest.raises(MarketDataIntegrityError, match="2026-09-11"):
        validate_daily_context(context(), "2026-09-11")


def test_complete_dated_bar_passes():
    validate_daily_context(context(), "2026-09-10")


@pytest.mark.parametrize("changes", [
    {"open": 26.38, "high": 26.36, "low": 26.36, "close": 26.36},
    {"is_estimated": True}, {"close": float("nan")}, {"low": None},
    {"is_partial_bar": True}, {"date": "not-a-date"},
])
def test_invalid_bar_blocks(changes):
    data = context()
    data["today"].update(changes)
    with pytest.raises(MarketDataIntegrityError):
        validate_daily_context(data, "2026-09-10")


def test_weekend_quote_does_not_overwrite_daily_context():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh")
    pipeline.search_service = SimpleNamespace(news_window_days=3)
    pipeline.fetcher_manager = MagicMock()
    original = context()
    saved = copy.deepcopy(original)
    quote = SimpleNamespace(price=26.36, source="akshare_em")
    trend = MagicMock(ma5=27.032, ma10=27.366, ma20=27.354)
    result = pipeline._enhance_context(
        original, quote, None, trend,
        market_phase_context={"phase": "non_trading", "is_partial_bar": False},
    )
    assert result["today"] == saved["today"]
    assert result["yesterday"] == saved["yesterday"]
    assert result["date"] == "2026-09-10"
    assert original == saved


def test_percentage_conflict_blocks():
    data = context()
    data["today"]["pct_chg"] = 1.70
    with pytest.raises(MarketDataIntegrityError, match="percentage"):
        validate_daily_context(data)


def test_bias_conflict_blocks():
    data = context()
    data["today"]["ma5"] = 27.032
    data["trend_analysis"] = {"bias_ma5": -2.49}
    with pytest.raises(MarketDataIntegrityError, match="bias"):
        validate_daily_context(data)


@pytest.mark.parametrize("news, evidence", [(None, False), ("   ", False),
                                           ("未找到相关信息", False)])
def test_missing_news_stops_before_model_initialization(news, evidence):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    data = context()
    data["news_evidence_present"] = evidence
    with pytest.raises(MarketDataIntegrityError, match="news evidence missing"):
        analyzer.analyze(data, news_context=news)


def test_stale_session_stops_before_model_initialization():
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    data = context()
    data["market_phase_context"] = {"effective_daily_bar_date": "2026-09-11"}
    with pytest.raises(MarketDataIntegrityError, match="daily_bar_date"):
        analyzer.analyze(data, news_context="test evidence")
