from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends

from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.api.v1.dependencies import (
    get_market_data_source,
    get_news_analysis_service,
    get_stock_service,
)
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema, StockNewsSchema
from backend.app.services.analysis_context import NewsAnalysisService
from backend.app.services.market_data_service import (
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataSource,
)
from backend.app.services.stock_service import StockService
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS

router = APIRouter()

_SUPPORTED_PERIOD = "daily"


@router.get("/stocks/search", response_model=ApiResponse[List[StockBasicSchema]])
def search_stocks(
    keyword: str,
    service: StockService = Depends(get_stock_service),
) -> ApiResponse[List[StockBasicSchema]]:
    if not keyword.strip():
        raise InvalidParameterError("keyword must not be empty")
    try:
        data = service.search_stocks(keyword)
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}", response_model=ApiResponse[StockBasicSchema])
def get_stock_info(
    stock_code: str,
    service: StockService = Depends(get_stock_service),
) -> ApiResponse[StockBasicSchema]:
    try:
        data = service.get_stock_info(stock_code)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}/kline", response_model=ApiResponse[List[DailyKlineSchema]])
def get_stock_kline(
    stock_code: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    period: str = "daily",
    market_data_source: MarketDataSource = Depends(get_market_data_source),
) -> ApiResponse[List[DailyKlineSchema]]:
    if period != _SUPPORTED_PERIOD:
        raise InvalidParameterError("V1 kline only supports the daily period")
    try:
        data = market_data_source.query_daily(
            stock_code,
            start_date,
            end_date,
            min_rows=DEFAULT_MIN_KLINE_ROWS,
            max_stale_days=DEFAULT_MAX_STALE_DAYS,
            max_gap_days=DEFAULT_MAX_GAP_DAYS,
        )
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}/news", response_model=ApiResponse[List[StockNewsSchema]])
def get_stock_news(
    stock_code: str,
    limit: int = 10,
    service: NewsAnalysisService = Depends(get_news_analysis_service),
) -> ApiResponse[List[StockNewsSchema]]:
    if limit < 1 or limit > 50:
        raise InvalidParameterError("limit must be between 1 and 50")
    try:
        items = service.get_news(stock_code, limit)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(
        data=[StockNewsSchema(stock_code=stock_code, **item.model_dump()) for item in items]
    )
