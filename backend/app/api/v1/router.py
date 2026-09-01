from fastapi import APIRouter

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.health import HealthData
from backend.app.api.v1.ai_analysis import router as ai_analysis_router

api_router = APIRouter()
api_router.include_router(ai_analysis_router)


@api_router.get("/health", response_model=ApiResponse[HealthData])
def health_check() -> ApiResponse[HealthData]:
    return ApiResponse(data=HealthData(status="ok"))
