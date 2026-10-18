"""PLASTIFY System Diagnostic API Endpoints."""

from typing import Annotated
from fastapi import APIRouter, Depends

from app.core.dependencies import RequestIDDep, SettingsDep
from app.schemas.system import PingResponse, SystemInfoResponse
from app.services.system import SystemService

router = APIRouter(prefix="/system", tags=["System Diagnostics"])


def get_system_service(settings: SettingsDep) -> SystemService:
    """Dependency provider for SystemService."""
    return SystemService(settings=settings)


SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]


@router.get(
    "/info",
    response_model=SystemInfoResponse,
    summary="System Information",
    description="Returns application environment, version, and runtime diagnostics.",
)
async def system_info(
    service: SystemServiceDep,
) -> SystemInfoResponse:
    """Retrieve system diagnostics."""
    return service.get_system_info()


@router.get(
    "/ping",
    response_model=PingResponse,
    summary="Ping Endpoint",
    description="Simple diagnostic heartbeat returning pong and the correlation ID.",
)
async def ping(
    request_id: RequestIDDep,
    service: SystemServiceDep,
) -> PingResponse:
    """Respond to ping."""
    return service.ping(request_id=request_id)
