from fastapi import APIRouter, Depends

from backend.app.api.v1.dependencies import get_ai_analysis_service
from backend.app.schemas.ai import AIAnalysisData, AIAnalyzeRequest
from backend.app.schemas.common import ApiResponse
from backend.app.services.ai_analysis import AIAnalysisService


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze", response_model=ApiResponse[AIAnalysisData])
async def analyze_stock(
    request: AIAnalyzeRequest,
    service: AIAnalysisService = Depends(get_ai_analysis_service),
) -> ApiResponse[AIAnalysisData]:
    result = await service.analyze(request.stock_code)
    return ApiResponse(data=result)
