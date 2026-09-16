# -*- coding: utf-8 -*-
"""
===================================
服务层模块初始化
===================================

职责：
1. 声明可导出的服务类（延迟导入，避免启动时拉入 LLM 等重依赖）
2. 暴露 DSA canonical 新闻/行情信源注册表（同样延迟导入）

使用方式：
    直接从子模块导入，例如:
    from src.services.history_service import HistoryService

    或从服务层读取统一信源治理:
    from src.services import load_source_channel_catalog, ordered_news_transport_ids
"""


def __getattr__(name: str):
    """延迟导入：仅在通过 src.services.X 访问时才加载对应子模块。"""
    _lazy_map = {
        "AnalysisService": "src.services.analysis_service",
        "BacktestService": "src.services.backtest_service",
        "HistoryService": "src.services.history_service",
        "StockService": "src.services.stock_service",
        "TaskService": "src.services.task_service",
        "get_task_service": "src.services.task_service",
        "load_source_channel_catalog": "src.services.source_channel_registry",
        "ordered_news_transport_ids": "src.services.source_channel_registry",
        "news_channel_for_url": "src.services.source_channel_registry",
        "news_evidence_rank": "src.services.source_channel_registry",
        "source_channel_governance": "src.services.source_channel_registry",
        "source_channel_summary": "src.services.source_channel_registry",
    }
    if name in _lazy_map:
        import importlib
        module = importlib.import_module(_lazy_map[name])
        return getattr(module, name)
    raise AttributeError(f"module 'src.services' has no attribute {name!r}")


__all__ = [
    "AnalysisService",
    "BacktestService",
    "HistoryService",
    "StockService",
    "TaskService",
    "get_task_service",
    "load_source_channel_catalog",
    "ordered_news_transport_ids",
    "news_channel_for_url",
    "news_evidence_rank",
    "source_channel_governance",
    "source_channel_summary",
]
