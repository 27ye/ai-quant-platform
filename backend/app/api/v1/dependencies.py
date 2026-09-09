from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.ai.client import LLMClient, OpenAICompatibleLLMClient
from backend.app.core.config import get_settings
from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import StockDataProvider
from backend.app.db.session import get_db
from backend.app.services.ai_analysis import (
    AIAnalysisService,
    SQLAlchemyAIAnalysisRepository,
)
from backend.app.services.ai_context_adapter import StockQuantAnalysisAdapter
from backend.app.services.market_data_service import (
    MarketDataRepository, MarketDataService, MarketDataSource,
)
from backend.app.services.news_service import NewsRepository, NewsService
from backend.app.services.stock_service import StockService
from backend.app.services.analysis_context import (
    AnalysisContextProvider,
    BacktestAnalysisService,
    NewsAnalysisService,
    QuantAnalysisService,
    ServiceAnalysisContextProvider,
    StockAnalysisService,
)


def get_data_provider() -> StockDataProvider:
    return AKShareStockProvider()


def get_stock_service(
    provider: StockDataProvider = Depends(get_data_provider),
) -> StockService:
    return StockService(provider=provider)


def get_market_data_source(
    stock_service: StockService = Depends(get_stock_service),
    db: Session = Depends(get_db),
) -> MarketDataSource:
    return MarketDataService(stock_service=stock_service, repository=MarketDataRepository(db))


def get_stock_quant_analysis_adapter(
    market_data_source: MarketDataSource = Depends(get_market_data_source),
    stock_service: StockService = Depends(get_stock_service),
) -> StockQuantAnalysisAdapter:
    return StockQuantAnalysisAdapter(
        market_data_source=market_data_source, stock_service=stock_service,
    )


def get_stock_analysis_service(
    adapter: StockQuantAnalysisAdapter = Depends(get_stock_quant_analysis_adapter),
) -> StockAnalysisService:
    return adapter


def get_quant_analysis_service(
    adapter: StockQuantAnalysisAdapter = Depends(get_stock_quant_analysis_adapter),
) -> QuantAnalysisService:
    return adapter


def get_backtest_analysis_service(
    adapter: StockQuantAnalysisAdapter = Depends(get_stock_quant_analysis_adapter),
) -> BacktestAnalysisService:
    return adapter


def get_news_analysis_service(
    provider: StockDataProvider = Depends(get_data_provider),
    db: Session = Depends(get_db),
) -> NewsAnalysisService:
    return NewsService(provider=provider, repository=NewsRepository(db))


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


def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_name=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def get_ai_analysis_service(
    context_provider: AnalysisContextProvider = Depends(get_analysis_context_provider),
    db: Session = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
) -> AIAnalysisService:
    return AIAnalysisService(
        context_provider=context_provider,
        llm_client=llm_client,
        repository=SQLAlchemyAIAnalysisRepository(db),
    )
