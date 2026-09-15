from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from backend.app.api.v1.dependencies import get_backtest_repository, get_backtest_service, get_quant_service
from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.schemas.backtest import BacktestRequestSchema
from backend.app.schemas.common import ApiResponse
from backend.app.services.backtest_service import BacktestRepository, BacktestService
from backend.app.services.quant_service import QuantService

router = APIRouter()


@router.get("/stocks/{stock_code}/indicators", response_model=ApiResponse[List[Dict[str, Any]]])
def get_stock_indicators(
    stock_code: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    service: QuantService = Depends(get_quant_service),
) -> ApiResponse[List[Dict[str, Any]]]:
    try:
        data = service.get_indicators(stock_code, start_date, end_date)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/stocks/{stock_code}/score", response_model=ApiResponse[Dict[str, Any]])
def get_stock_score(
    stock_code: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    service: QuantService = Depends(get_quant_service),
) -> ApiResponse[Dict[str, Any]]:
    try:
        data = service.get_score(stock_code, start_date, end_date)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.post("/backtests", response_model=ApiResponse[Dict[str, Any]])
def run_stock_backtest(
    request: BacktestRequestSchema,
    service: BacktestService = Depends(get_backtest_service),
) -> ApiResponse[Dict[str, Any]]:
    """Run a backtest and return its saved ``backtest_id``.

    ``parameters`` presence selects the semantics: omitted keeps V1 behaviour
    (``v1_legacy``), present (even ``{}``) means ``v2_windowed``. Invalid or
    unknown parameters are rejected before any data is fetched (``40001``).
    """
    try:
        data = service.run(
            stock_code=request.stock_code,
            start_date=request.start_date,
            end_date=request.end_date,
            parameters=request.parameters,
            parameters_provided=request.parameters_provided,
        )
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/backtests", response_model=ApiResponse[Dict[str, Any]])
def list_backtests(
    stock_code: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    repository: BacktestRepository = Depends(get_backtest_repository),
) -> ApiResponse[Dict[str, Any]]:
    """Paginated history summaries - reads saved rows only, never recomputes."""
    if stock_code is not None and (
        len(stock_code) != 6 or not stock_code.isdigit()
    ):
        raise InvalidParameterError("stock_code must be a 6-digit string")
    if page < 1 or page_size < 1 or page_size > 100:
        raise InvalidParameterError("page must be >= 1 and 1 <= page_size <= 100")
    items, total = repository.list(
        stock_code=stock_code, page=page, page_size=page_size
    )
    return ApiResponse(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.get("/backtests/{backtest_id}", response_model=ApiResponse[Dict[str, Any]])
def get_backtest(
    backtest_id: int,
    include_input_snapshot: bool = False,
    repository: BacktestRepository = Depends(get_backtest_repository),
) -> ApiResponse[Dict[str, Any]]:
    """Saved snapshot detail (parameters, curves, orders) - no refetch, no recompute.

    ``include_input_snapshot=true`` additionally returns the exact rows that were
    handed to C (warmup included); the default response only reports their count.
    """
    if backtest_id < 1:
        raise InvalidParameterError("backtest_id must be a positive integer")
    return ApiResponse(
        data=repository.get(
            backtest_id, include_input_snapshot=include_input_snapshot
        )
    )
