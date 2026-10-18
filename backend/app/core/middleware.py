"""PLASTIFY Core Middleware Components.

Handles correlation ID propagation, request timing, and structured access logging.
"""

import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logging import set_current_request_id

logger = logging.getLogger("plastify.access")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware for request correlation ID generation and latency measurement."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        header_name = settings.REQUEST_ID_HEADER

        # Extract existing correlation ID or generate a new UUID4
        request_id = request.headers.get(header_name) or str(uuid.uuid4())
        set_current_request_id(request_id)

        # Store in request state for convenient access in endpoints
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Calculate duration even if error occurs
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"HTTP {request.method} {request.url.path} failed after {duration_ms:.2f}ms",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            set_current_request_id(None)
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Attach correlation headers to the response
        response.headers[header_name] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"

        # Structured access logging (skip health check liveness endpoints to prevent spam)
        if not request.url.path.endswith("/health/live"):
            logger.info(
                f"HTTP {request.method} {request.url.path} {response.status_code} ({duration_ms:.2f}ms)",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": request.client.host if request.client else None,
                },
            )

        # Clear context
        set_current_request_id(None)

        return response
