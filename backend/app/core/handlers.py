"""PLASTIFY Global Exception Handlers.

Catches and formats application exceptions, HTTP errors, validation errors,
and unexpected server errors into standardized API response envelopes.
"""

import logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import PlastifyException
from app.core.logging import get_current_request_id
from app.schemas.common import APIErrorResponse, ErrorDetail

logger = logging.getLogger("plastify.handlers")


def register_exception_handlers(app: FastAPI, debug: bool = False) -> None:
    """Register all global exception handlers on the FastAPI application instance."""

    @app.exception_handler(PlastifyException)
    async def plastify_exception_handler(request: Request, exc: PlastifyException) -> JSONResponse:
        request_id = get_current_request_id()
        logger.warning(
            f"Handled PlastifyException: [{exc.error_code}] {exc.message}",
            extra={"error_code": exc.error_code, "status_code": exc.status_code, "details": exc.details},
        )
        error_response = APIErrorResponse(
            error=ErrorDetail(code=exc.error_code, message=exc.message, details=exc.details or None),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = get_current_request_id()
        formatted_errors = []
        for error in exc.errors():
            formatted_errors.append(
                {
                    "loc": [str(loc_item) for loc_item in error.get("loc", [])],
                    "msg": error.get("msg"),
                    "type": error.get("type"),
                }
            )

        logger.info(
            f"Validation error on {request.method} {request.url.path}",
            extra={"validation_errors": formatted_errors},
        )
        error_response = APIErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="One or more request parameters failed validation.",
                details={"errors": formatted_errors},
            ),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_response.model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = get_current_request_id()
        error_response = APIErrorResponse(
            error=ErrorDetail(
                code=f"HTTP_{exc.status_code}",
                message=str(exc.detail) if exc.detail else "HTTP Exception occurred",
            ),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = get_current_request_id()
        logger.exception(
            f"Unhandled exception during {request.method} {request.url.path}: {str(exc)}",
            extra={"path": request.url.path, "method": request.method},
        )
        message = (
            f"An unexpected internal error occurred: {str(exc)}"
            if debug
            else "An unexpected internal server error occurred."
        )
        error_response = APIErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message=message,
                details={"type": type(exc).__name__} if debug else None,
            ),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response.model_dump(mode="json"),
        )
