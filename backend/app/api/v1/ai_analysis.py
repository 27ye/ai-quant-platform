from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from backend.app.api.v1.dependencies import (
    get_ai_analysis_service,
    get_ai_report_history_service,
)
from backend.app.core.errors import ReportNotFoundError
from backend.app.schemas.ai import AIAnalyzeRequest, AIReportDetail, PaginatedAIReports
from backend.app.schemas.common import ApiResponse
from backend.app.services.ai_analysis import AIAnalysisService, AIReportHistoryService


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze", response_model=ApiResponse[AIReportDetail])
async def analyze_stock(
    request: AIAnalyzeRequest,
    service: AIAnalysisService = Depends(get_ai_analysis_service),
) -> ApiResponse[AIReportDetail]:
    result = (
        await service.analyze(request.stock_code, backtest_id=request.backtest_id)
        if request.backtest_id is not None
        else await service.analyze(request.stock_code)
    )
    return ApiResponse(data=result)


@router.get("/reports", response_model=ApiResponse[PaginatedAIReports])
def list_reports(
    stock_code: Optional[str] = Query(default=None, pattern=r"^\d{6}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: AIReportHistoryService = Depends(get_ai_report_history_service),
) -> ApiResponse[PaginatedAIReports]:
    return ApiResponse(data=service.list_reports(stock_code, page, page_size))


@router.get("/reports/{report_id}", response_model=ApiResponse[AIReportDetail])
def get_report(
    report_id: int = Path(gt=0),
    service: AIReportHistoryService = Depends(get_ai_report_history_service),
) -> ApiResponse[AIReportDetail]:
    report = service.get_report(report_id)
    if report is None:
        raise ReportNotFoundError()
    return ApiResponse(data=report)
