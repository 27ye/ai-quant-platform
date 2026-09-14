from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.db.session import get_db
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema, StockNewsSchema
from backend.app.services.news_service import NewsRepository, NewsService
from backend.app.services.stock_service import StockService

router = APIRouter()
_service = StockService()

_SUPPORTED_PERIOD = "daily"


@router.get("/stocks/search", response_model=ApiResponse[List[StockBasicSchema]])
def search_stocks(keyword: str) -> ApiResponse[List[StockBasicSchema]]:
    if not keyword.strip():
        raise InvalidParameterError("keyword must not be empty")
    try:
        data = _service.search_stocks(keyword)
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}", response_model=ApiResponse[StockBasicSchema])
def get_stock_info(stock_code: str) -> ApiResponse[StockBasicSchema]:
    try:
        data = _service.get_stock_info(stock_code)
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
) -> ApiResponse[List[DailyKlineSchema]]:
    if period != _SUPPORTED_PERIOD:
        raise InvalidParameterError("V1 kline only supports the daily period")
    try:
        data = _service.get_daily_kline(stock_code, start_date, end_date)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}/news", response_model=ApiResponse[List[StockNewsSchema]])
def get_stock_news(
    stock_code: str,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> ApiResponse[List[StockNewsSchema]]:
    if limit < 1 or limit > 50:
        raise InvalidParameterError("limit must be between 1 and 50")
    service = NewsService(repository=NewsRepository(db))
    try:
        items = service.get_news(stock_code, limit)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(
        data=[StockNewsSchema(stock_code=stock_code, **item.model_dump()) for item in items]
    )
