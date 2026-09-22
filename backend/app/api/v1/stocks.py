from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.api.v1.dependencies import (
    get_data_status_service,
    get_market_data_source,
    get_news_analysis_service,
    get_stock_catalog_service,
    get_stock_service,
)
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.stock import (
    DailyKlineSchema,
    StockBasicSchema,
    StockDataStatusSchema,
    StockNewsSchema,
)
from backend.app.services.analysis_context import NewsAnalysisService
from backend.app.services.data_status_service import DataStatusService
from backend.app.services.market_data_service import (
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataSource,
)
from backend.app.services.stock_catalog_service import StockCatalogService
from backend.app.services.stock_service import StockService
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS

router = APIRouter()

_SUPPORTED_PERIOD = "daily"


@router.get("/stocks/search", response_model=ApiResponse[List[StockBasicSchema]])
def search_stocks(
    keyword: str,
    service: StockCatalogService = Depends(get_stock_catalog_service),
) -> ApiResponse[List[StockBasicSchema]]:
    """Search the synced local catalog; the provider is never called here.

    Response shape is unchanged from V1. A catalog that has been synced successfully
    answers locally (an empty list is a genuine "no match"), and it keeps answering
    even if the most recent *refresh* failed - that error stays visible through
    ``last_error`` on ``/data-status``. Only a catalog that has **never** been synced
    has nothing to search, and that is reported as ``50006`` (HTTP 503,
    ``stock catalog not synced``) instead of a misleading provider error.
    """
    try:
        data = service.search(keyword)
    except InvalidParameterError:
        raise
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/stocks/catalog/sync", response_model=ApiResponse[Dict[str, Any]])
def sync_stock_catalog(
    service: StockCatalogService = Depends(get_stock_catalog_service),
) -> ApiResponse[Dict[str, Any]]:
    """Explicitly (re)sync the local stock catalog - the trigger that was missing.

    V2 B1 froze *search* as a local-only read that must never call the provider, and the
    sync was reachable only through ``scripts/sync_stock_catalog.py``. Nothing in the
    running service ever called ``StockCatalogService.sync()``, so a real backend started
    with an empty catalog and answered **every** search with ``50006`` (A, PR #23 review).
    This endpoint is that missing trigger. It stays **outside** the search path: search
    still answers from MySQL only, and never calls the provider.

    Calling it repeatedly is a refresh, not an append. A failed refresh is reported
    honestly as ``50001``/``502`` and leaves an already-synced catalog fully searchable -
    only a catalog that has **never** been synced yields ``50006``.
    """
    try:
        result = service.sync()
    except InvalidParameterError:
        raise
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(
        data={
            "row_count": result.row_count,
            "source": result.source,
            "synced_at": result.synced_at.isoformat() if result.synced_at else None,
            "catalog_complete": service.is_catalog_usable(),
        }
    )


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


@router.get(
    "/stocks/{stock_code}/data-status",
    response_model=ApiResponse[StockDataStatusSchema],
)
def get_stock_data_status(
    stock_code: str,
    service: DataStatusService = Depends(get_data_status_service),
) -> ApiResponse[StockDataStatusSchema]:
    """Catalog + daily-bar provenance, coverage and freshness for one stock.

    Reports ``mode="unknown"`` when no refresh metadata exists and
    ``coverage="unknown"`` when the trading calendar cannot prove the expected
    bar count - neither is guessed from dates or natural days.
    """
    try:
        data = service.get_status(stock_code)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    return ApiResponse(data=data)
