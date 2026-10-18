"""PLASTIFY System Schemas."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class SystemInfoResponse(BaseModel):
    """System information payload."""

    app_name: str = Field(..., description="Application name")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Environment")
    api_prefix: str = Field(..., description="API prefix route")
    python_version: str = Field(..., description="Python runtime version")
    debug_mode: bool = Field(..., description="Whether debug mode is active")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PingResponse(BaseModel):
    """Simple ping-pong response."""

    message: str = Field(default="pong", description="Ping response text")
    request_id: Optional[str] = Field(default=None, description="Request correlation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
