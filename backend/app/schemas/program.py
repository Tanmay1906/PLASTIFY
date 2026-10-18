"""PLASTIFY Corporate Program Pydantic Schemas."""

from datetime import datetime, timezone
from typing import List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.program import ProgramStatus


class ProgramCreateRequest(BaseModel):
    """Payload for creating a corporate plastic recovery program."""

    name: str = Field(..., min_length=2, max_length=200, description="Program title")
    description: Optional[str] = Field(default=None, description="Detailed program objectives")
    region: str = Field(
        default="GLOBAL", min_length=2, max_length=50, description="Operational region code (e.g. DEL, MUM, SEA)"
    )
    target_kg: float = Field(..., gt=0, description="Total recovery target in kilograms")
    allowed_material_types: List[str] = Field(
        ..., min_length=1, description="List of accepted resin types (e.g. ['PET', 'HDPE'])"
    )
    start_date: Optional[datetime] = Field(
        default=None, description="Program launch timestamp. Defaults to current time."
    )
    end_date: Optional[datetime] = Field(default=None, description="Program completion timestamp")
    status: Optional[ProgramStatus] = Field(
        default=ProgramStatus.DRAFT, description="Initial program lifecycle status"
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "ProgramCreateRequest":
        if self.start_date is None:
            self.start_date = datetime.now(timezone.utc)
        if self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be strictly after start_date.")
        return self


class ProgramUpdateRequest(BaseModel):
    """Payload for modifying a corporate plastic recovery program."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = None
    region: Optional[str] = Field(default=None, min_length=2, max_length=50)
    target_kg: Optional[float] = Field(default=None, gt=0)
    allowed_material_types: Optional[List[str]] = Field(default=None, min_length=1)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[ProgramStatus] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "ProgramUpdateRequest":
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be strictly after start_date.")
        return self


class ProgramResponse(BaseModel):
    """Public representation of a plastic recovery program."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: Optional[str] = None
    name: str
    description: Optional[str] = None
    region: str
    target_kg: float
    collected_kg: float
    progress_percent: float = 0.0
    allowed_material_types: List[str]
    start_date: datetime
    end_date: Optional[datetime] = None
    status: ProgramStatus
    created_at: datetime
    updated_at: datetime


class ProgramPartnerAssignRequest(BaseModel):
    """Payload to assign an operational partner organization to a Program."""

    organization_id: uuid.UUID = Field(
        ..., description="Partner organization ID (e.g. Collector, Logistics)"
    )
    assigned_role: str = Field(
        default="COLLECTOR", description="Operational role in program"
    )


class ProgramPartnerResponse(BaseModel):
    """Operational partner assignment representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: Optional[str] = None
    assigned_role: str
    is_active: bool
    created_at: datetime
