"""Exercise real consumer entry points with an authentic rejected model output."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.services.analysis_service import AnalysisService
from src.services.market_data_integrity import enforce_daily_report


def rejected():
    fixture = json.loads((Path(__file__).parent/'fixtures/xiaomi_model_followup_unapproved_20260912.json').read_text())
    data = fixture['result']
    obj = SimpleNamespace(**data, to_dict=lambda: data)
    enforce_daily_report(obj, fixture['context'])
    assert not obj.success
    return obj


def test_failed_real_output_never_reaches_single_or_aggregate_notification():
    obj = rejected()
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notifier = MagicMock()
    pipeline._send_single_stock_notification(obj)
    pipeline._send_notifications([obj])
    assert not pipeline.notifier.mock_calls
    assert pipeline._save_local_report([obj]) is None
    assert not pipeline.notifier.mock_calls


def test_api_and_web_serializer_reject_failed_real_output():
    obj = rejected()
    service = AnalysisService.__new__(AnalysisService)
    with pytest.raises(ValueError, match='API/Web'):
        service._build_analysis_response(obj, 'contract-replay')
    with patch('src.core.pipeline.StockAnalysisPipeline') as factory, patch('src.config.get_config'):
        factory.return_value.process_single_stock.return_value = obj
        assert service.analyze_stock('hk01810', send_notification=False) is None
        assert service.last_error


def test_a_rejected_audit_cannot_be_bypassed_by_toggling_success():
    obj = rejected(); obj.success = True
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notifier = MagicMock()
    with pytest.raises(ValueError, match='accepted report'):
        pipeline._generate_aggregate_report([obj], ReportType.BRIEF)
    assert not pipeline.notifier.mock_calls
