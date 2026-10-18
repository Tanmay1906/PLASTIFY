"""PLASTIFY Backend Main Application Entrypoint.

Modular monolith backend foundation for plastic recovery verification
and circular-economy tracking.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import close_db_engine
from app.core.handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestCorrelationMiddleware
from app.core.redis import close_redis

settings = get_settings()
logger = setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager controlling startup and shutdown tasks."""
    logger.info(
        f"Starting {settings.PROJECT_NAME} v{settings.VERSION} [{settings.ENVIRONMENT}]",
        extra={"version": settings.VERSION, "environment": settings.ENVIRONMENT},
    )

    yield

    logger.info("Initiating graceful shutdown...")
    # Clean up backing service connection pools
    await close_redis()
    await close_db_engine()
    logger.info("Shutdown completed successfully")


def create_application() -> FastAPI:
    """FastAPI application factory with configuration, middleware, and routers."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Health & Readiness", "description": "Liveness, readiness, and dependency probes"},
            {"name": "System Diagnostics", "description": "System health, metadata, and telemetry"},
        ],
    )

    # 1. Add Request Correlation ID Middleware (outermost for accurate timing)
    app.add_middleware(RequestCorrelationMiddleware)

    # 2. Add CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[settings.REQUEST_ID_HEADER, "X-Process-Time"],
    )

    # 3. Register Global Exception Handlers
    register_exception_handlers(app, debug=settings.DEBUG)

    # 4. Mount API Routers
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    # 5. Root Entrypoint
    @app.get("/", tags=["System Diagnostics"], summary="Root Discovery")
    async def root_discovery() -> JSONResponse:
        """Root discovery endpoint providing links to documentation and health status."""
        return JSONResponse(
            content={
                "name": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
                "docs": "/docs",
                "openapi": "/openapi.json",
                "health": f"{settings.API_V1_STR}/health",
            }
        )

    # Optional root /health shortcut alias redirecting to /api/v1/health
    @app.get("/health", tags=["Health & Readiness"], include_in_schema=False)
    async def root_health_alias() -> JSONResponse:
        """Convenience alias for load balancers expecting /health at root."""
        return JSONResponse(content={"status": "live", "canonical_url": f"{settings.API_V1_STR}/health"})

    return app


app = create_application()
