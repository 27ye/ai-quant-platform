from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.ai.errors import AIServiceError
from backend.app.core.errors import ApplicationError
from backend.app.schemas.common import ApiResponse


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(400, 40001, "invalid parameter")

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(AIServiceError)
    async def handle_ai_service_error(
        request: Request,
        exc: AIServiceError,
    ) -> JSONResponse:
        return _error_response(500, 50005, "ai service error")


def _error_response(status_code: int, code: int, message: str) -> JSONResponse:
    body = ApiResponse[object](code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))
