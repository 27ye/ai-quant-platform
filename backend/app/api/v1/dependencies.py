from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.ai.client import OpenAICompatibleLLMClient
from backend.app.core.config import get_settings
from backend.app.core.errors import InsufficientStockDataError
from backend.app.db.session import get_db
from backend.app.services.ai_analysis import (
    AIAnalysisService,
    SQLAlchemyAIAnalysisRepository,
)
from backend.app.services.analysis_context import (
    AnalysisContextProvider,
    BacktestAnalysisService,
    NewsAnalysisService,
    QuantAnalysisService,
    ServiceAnalysisContextProvider,
    StockAnalysisService,
)


def get_stock_analysis_service() -> StockAnalysisService:
    raise InsufficientStockDataError("stock service integration is not configured")


def get_quant_analysis_service() -> QuantAnalysisService:
    raise InsufficientStockDataError("quant service integration is not configured")


def get_backtest_analysis_service() -> BacktestAnalysisService:
    raise InsufficientStockDataError("backtest service integration is not configured")


def get_news_analysis_service() -> NewsAnalysisService:
    raise InsufficientStockDataError("news service integration is not configured")


def get_analysis_context_provider(
    stock_service: StockAnalysisService = Depends(get_stock_analysis_service),
    quant_service: QuantAnalysisService = Depends(get_quant_analysis_service),
    backtest_service: BacktestAnalysisService = Depends(get_backtest_analysis_service),
    news_service: NewsAnalysisService = Depends(get_news_analysis_service),
) -> AnalysisContextProvider:
    return ServiceAnalysisContextProvider(
        stock_service=stock_service,
        quant_service=quant_service,
        backtest_service=backtest_service,
        news_service=news_service,
    )


def get_ai_analysis_service(
    context_provider: AnalysisContextProvider = Depends(get_analysis_context_provider),
    db: Session = Depends(get_db),
) -> AIAnalysisService:
    settings = get_settings()
    llm_client = OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_name=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return AIAnalysisService(
        context_provider=context_provider,
        llm_client=llm_client,
        repository=SQLAlchemyAIAnalysisRepository(db),
    )
