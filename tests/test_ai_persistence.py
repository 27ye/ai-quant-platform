import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.errors import DatabaseOperationError
from backend.app.schemas.ai import AIAnalysisData
from backend.app.services.ai_analysis import SQLAlchemyAIAnalysisRepository


class RecordingSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")


def test_repository_maps_api_schema_to_ai_analysis_model():
    session = RecordingSession()
    repository = SQLAlchemyAIAnalysisRepository(session)
    result = AIAnalysisData(
        stock_code="600519",
        quant_score=82,
        trend="bullish",
        summary="趋势偏强。",
        technical_analysis="技术指标整体偏强。",
        quant_analysis="量化评分较高。",
        news_analysis="新闻信息整体中性。",
        advantages=["品牌优势"],
        risks=["市场波动"],
        conclusion="结合风险承受能力审慎判断。",
        model_name="test-model",
    )

    repository.save(result)

    assert session.committed is True
    assert len(session.added) == 1
    record = session.added[0]
    assert record.stock_code == "600519"
    assert record.advantages == ["品牌优势"]
    assert record.model_name == "test-model"


def test_repository_rolls_back_database_failure():
    class FailingSession(RecordingSession):
        def __init__(self):
            super().__init__()
            self.rolled_back = False

        def commit(self):
            raise SQLAlchemyError("commit failed")

        def rollback(self):
            self.rolled_back = True

    session = FailingSession()
    repository = SQLAlchemyAIAnalysisRepository(session)
    result = AIAnalysisData(
        stock_code="600519",
        quant_score=None,
        trend="neutral",
        summary="信息有限。",
        technical_analysis="技术数据有限。",
        quant_analysis="量化评分缺失。",
        news_analysis="新闻数据有限。",
        advantages=["已明确数据边界"],
        risks=["数据不足"],
        conclusion="等待更多真实数据。",
        model_name="test-model",
    )

    with pytest.raises(DatabaseOperationError):
        repository.save(result)

    assert session.rolled_back is True
