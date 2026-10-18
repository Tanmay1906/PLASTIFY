"""PLASTIFY SENTINEL Pydantic v2 Schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.sentinel import RiskLevel, SentinelStatus


class SentinelFlagBase(BaseModel):
    """Base payload for a Sentinel anomaly flag."""

    detector: str = Field(..., max_length=100, description="Identifier of the executing detector rule")
    severity: RiskLevel = Field(..., description="Risk severity tier (LOW, MEDIUM, HIGH, CRITICAL)")
    reason: str = Field(..., description="Detailed explanation of the risk signal or anomaly")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence certainty [0.0 - 1.0]")
    evidence_reference: Optional[str] = Field(
        default=None, max_length=255, description="Associated evidence or entity identifier"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Granular analytical findings and measurements"
    )


class SentinelFlagCreate(SentinelFlagBase):
    """Internal model for instantiating a new Sentinel flag."""

    pass


class SentinelFlagResponse(SentinelFlagBase):
    """Public representation of an individual Sentinel finding."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    result_id: uuid.UUID
    created_at: datetime


class SentinelResultResponse(BaseModel):
    """Complete public representation of a Sentinel risk assessment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recovery_id: uuid.UUID
    recovery_human_id: Optional[str] = None
    risk_score: float = Field(..., ge=0.0, le=100.0, description="Composite risk score [0 - 100]")
    risk_level: RiskLevel = Field(..., description="Categorical risk tier (LOW, MEDIUM, HIGH, CRITICAL)")
    summary: str = Field(..., description="Executive risk synthesis for verifiers")
    flags_count: int = Field(default=0, description="Total number of risk flags identified")
    critical_count: int = Field(default=0, description="Count of CRITICAL severity flags")
    high_count: int = Field(default=0, description="Count of HIGH severity flags")
    medium_count: int = Field(default=0, description="Count of MEDIUM severity flags")
    low_count: int = Field(default=0, description="Count of LOW severity flags")
    status: SentinelStatus = Field(default=SentinelStatus.COMPLETED, description="Analysis completion status")
    flags: List[SentinelFlagResponse] = Field(default_factory=list, description="Granular detector flags")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Execution benchmarks and diagnostics")
    created_at: datetime
    updated_at: datetime


class SentinelRunRequest(BaseModel):
    """Request payload to trigger Sentinel risk analysis."""

    async_run: bool = Field(
        default=False,
        description="Whether to queue processing via Celery background workers",
    )
    detector_options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime parameters or tolerance overrides",
    )
