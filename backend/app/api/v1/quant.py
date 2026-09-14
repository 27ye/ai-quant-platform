from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.v1.dependencies import get_quant_service
from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.schemas.common import ApiResponse
from backend.app.services.quant_service import QuantService

router = APIRouter()


class BacktestRequest(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None


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
    request: BacktestRequest,
    service: QuantService = Depends(get_quant_service),
) -> ApiResponse[Dict[str, Any]]:
    try:
        data = service.run_backtest(request.stock_code, request.start_date, request.end_date)
    except InvalidStockCodeError as exc:
        raise InvalidParameterError(str(exc)) from exc
    except StockDataProviderError as exc:
        raise DataProviderError(str(exc)) from exc
    return ApiResponse(data=data)
