"""PLASTIFY Health and Readiness API Endpoints.

Implements liveness, readiness, and overall health probes for load balancers
and container orchestration.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import SettingsDep
from app.schemas.health import (
    HealthOverviewResponse,
    LivenessResponse,
    ReadinessResponse,
)
from app.services.health import HealthService

router = APIRouter(prefix="/health", tags=["Health & Readiness"])


def get_health_service(settings: SettingsDep) -> HealthService:
    """Dependency provider for HealthService."""
    return HealthService(settings=settings)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness Probe",
    description="Returns 200 if the FastAPI application process is alive and responsive.",
)
async def liveness_check(
    service: HealthServiceDep,
) -> LivenessResponse:
    """Fast in-memory liveness check."""
    return service.get_liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"description": "All infrastructure dependencies are healthy and accepting traffic."},
        503: {"description": "One or more infrastructure dependencies are unavailable."},
    },
    summary="Readiness Probe",
    description="Checks reachability of PostgreSQL and Redis backing services.",
)
async def readiness_check(
    response: Response,
    service: HealthServiceDep,
) -> ReadinessResponse:
    """Dependency connectivity readiness probe."""
    is_ready, data = await service.get_readiness()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return data


@router.get(
    "",
    response_model=HealthOverviewResponse,
    responses={
        200: {"description": "System is healthy."},
        503: {"description": "System or dependency degraded/unhealthy."},
    },
    summary="Health Overview",
    description="Returns comprehensive system status, version, uptime, and backing services health.",
)
async def health_overview(
    response: Response,
    service: HealthServiceDep,
) -> HealthOverviewResponse:
    """Full system diagnostics overview."""
    is_healthy, data = await service.get_health_overview()
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return data
