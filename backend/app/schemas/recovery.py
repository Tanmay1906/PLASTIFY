"""PLASTIFY Plastic Collection and Recovery Pydantic Schemas."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.recovery import RecoveryStatus


class RecoveryCreateRequest(BaseModel):
    """Payload submitted by an authorized Collector to record a Recovery Event."""

    program_id: uuid.UUID = Field(..., description="Associated plastic recovery program ID")
    material_type: str = Field(..., min_length=2, max_length=50, description="Recovered polymer type (e.g. PET)")
    weight_kg: float = Field(..., gt=0, description="Gross recovered weight in kilograms (must be positive)")
    collection_location: str = Field(
        ..., min_length=2, max_length=255, description="Physical collection site / facility description"
    )
    collection_coordinates: Optional[Dict[str, float]] = Field(
        default=None, description="Optional GPS coordinates: {'latitude': float, 'longitude': float}"
    )
    collected_at: Optional[datetime] = Field(
        default=None, description="Timestamp of physical recovery. Defaults to current time."
    )
    notes: Optional[str] = Field(default=None, description="Collector operational observations")

    @model_validator(mode="after")
    def validate_collection_time(self) -> "RecoveryCreateRequest":
        if self.collected_at is None:
            self.collected_at = datetime.now(timezone.utc)
        elif self.collected_at > datetime.now(timezone.utc):
            raise ValueError("collected_at timestamp cannot be in the future.")
        return self


class RecoveryUpdateRequest(BaseModel):
    """Payload to modify an unsubmitted draft Recovery Event."""

    material_type: Optional[str] = Field(default=None, min_length=2, max_length=50)
    weight_kg: Optional[float] = Field(default=None, gt=0)
    collection_location: Optional[str] = Field(default=None, min_length=2, max_length=255)
    collection_coordinates: Optional[Dict[str, float]] = None
    collected_at: Optional[datetime] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_collection_time(self) -> "RecoveryUpdateRequest":
        if self.collected_at and self.collected_at > datetime.now(timezone.utc):
            raise ValueError("collected_at timestamp cannot be in the future.")
        return self


class RecoverySubmitRequest(BaseModel):
    """Payload to officially submit a draft recovery event for processing."""

    notes: Optional[str] = Field(default=None, description="Final submission remarks")


class RecoveryHistoryResponse(BaseModel):
    """Immutable audit entry of a state transition."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recovery_event_id: uuid.UUID
    from_status: Optional[str] = None
    to_status: str
    actor_id: uuid.UUID
    actor_role: str
    notes: Optional[str] = None
    event_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class RecoveryResponse(BaseModel):
    """Public representation of an auditable recovery event."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recovery_id: str = Field(..., description="Human-readable immutable ID (e.g. POP-DEL-2026-000184)")
    program_id: uuid.UUID
    program_name: Optional[str] = None
    collector_id: uuid.UUID
    collector_name: Optional[str] = None
    collector_organization_id: uuid.UUID
    collector_organization_name: Optional[str] = None
    material_type: str
    weight_kg: float
    collection_location: str
    collection_coordinates: Optional[Dict[str, float]] = None
    collected_at: datetime
    notes: Optional[str] = None
    status: RecoveryStatus
    custody_status: Optional[str] = None
    evidence_count: Optional[int] = 0
    created_at: datetime
    updated_at: datetime
    history: List[RecoveryHistoryResponse] = Field(default_factory=list)
