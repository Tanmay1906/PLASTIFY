"""PLASTIFY Health and Readiness Schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseModel, Field


class HealthState(str, Enum):
    """Health check state indicator."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of an infrastructure component (DB, Redis, etc.)."""

    status: HealthState = Field(..., description="Component operational status")
    latency_ms: Optional[float] = Field(default=None, description="Response time in milliseconds")
    details: Optional[str] = Field(default=None, description="Diagnostic details")
    error: Optional[str] = Field(default=None, description="Error message if unhealthy")


class LivenessResponse(BaseModel):
    """Fast probe response verifying process is responsive."""

    status: str = Field(default="live", description="Liveness status")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReadinessResponse(BaseModel):
    """Readiness probe response verifying dependencies are reachable."""

    status: HealthState = Field(..., description="Overall readiness status")
    components: Dict[str, ComponentHealth] = Field(
        ..., description="Status breakdown of backing services"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthOverviewResponse(BaseModel):
    """Comprehensive health check response."""

    status: HealthState = Field(..., description="Overall system health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Runtime environment")
    uptime_seconds: float = Field(..., description="Server process uptime")
    components: Dict[str, ComponentHealth] = Field(
        ..., description="Health status of external dependencies"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
