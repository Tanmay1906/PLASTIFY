"""PLASTIFY Impact Ledger, Methodology, and Eligibility Assessment Pydantic Schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.impact import AssessmentStatus, ImpactOutcomeType, ImpactStatus


# ------------------------------------------------------------------------------
# 1. Methodology Schemas
# ------------------------------------------------------------------------------

class MethodologyCreateRequest(BaseModel):
    """Payload to register a new carbon/plastic accounting standard or protocol."""

    code: str = Field(..., min_length=3, max_length=50, description="Unique identifier code, e.g. PLASTIFY-COL-v1")
    name: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10)
    standard_name: str = Field(default="PLASTIFY Environmental Protocol", max_length=150)
    is_standard_recognized: bool = Field(default=False, description="Flag indicating if recognized by formal third-party standard body")
    registry_name: Optional[str] = Field(default=None, max_length=100)


class MethodologyVersionCreateRequest(BaseModel):
    """Payload to define an immutable accounting version for a methodology."""

    version_tag: str = Field(..., min_length=1, max_length=50, description="e.g. 1.0.0")
    activity_type: ImpactOutcomeType = Field(..., description="Eligible physical activity: COLLECTION, RECYCLING_INPUT, RECYCLED_OUTPUT, etc.")
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    eligible_materials: List[str] = Field(..., min_length=1, description="List of eligible polymer types, e.g. ['PET', 'HDPE']")
    credit_conversion_factor: Decimal = Field(default=Decimal("0.001000"), gt=0, description="Credits generated per 1.000 KG (e.g. 0.001 = 1 Credit/MT)")
    credit_unit_name: str = Field(default="PLASTIC_RECOVERY_CREDIT", max_length=50)
    additionality_discount: Decimal = Field(default=Decimal("0.0000"), ge=0, le=1)
    baseline_discount: Decimal = Field(default=Decimal("0.0000"), ge=0, le=1)
    leakage_deduction: Decimal = Field(default=Decimal("0.0000"), ge=0, le=1)
    required_evidence_types: List[str] = Field(..., min_length=1, description="Required evidence keys, e.g. ['COLLECTION_PHOTO', 'WEIGHBRIDGE_RECEIPT']")
    requires_independent_verification: bool = Field(default=True)
    calculation_formula: Optional[str] = None
    disclaimer: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class MethodologyVersionResponse(BaseModel):
    """Public representation of an immutable methodology version."""

    id: uuid.UUID
    methodology_id: uuid.UUID
    version_tag: str
    activity_type: ImpactOutcomeType
    effective_from: datetime
    effective_to: Optional[datetime] = None
    is_immutable: bool
    eligible_materials: List[str]
    credit_conversion_factor: Decimal
    credit_unit_name: str
    additionality_discount: Decimal
    baseline_discount: Decimal
    leakage_deduction: Decimal
    required_evidence_types: List[str]
    requires_independent_verification: bool
    calculation_formula: str
    disclaimer: str
    parameters: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MethodologyResponse(BaseModel):
    """Public representation of a credit accounting methodology."""

    id: uuid.UUID
    code: str
    name: str
    description: str
    standard_name: str
    is_standard_recognized: bool
    registry_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    versions: List[MethodologyVersionResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 2. Impact Record Schemas
# ------------------------------------------------------------------------------

class ImpactRecordCreateRequest(BaseModel):
    """Payload to register an auditable impact record from a verified physical source."""

    outcome_type: ImpactOutcomeType
    source_recovery_id: Optional[uuid.UUID] = None
    source_material_batch_id: Optional[uuid.UUID] = None
    source_upcycling_batch_id: Optional[uuid.UUID] = None
    verification_record_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ImpactRecordSupersedeRequest(BaseModel):
    """Payload to traceably supersede an impact record with an audit correction."""

    new_quantity_kg: Decimal = Field(..., gt=0, description="Corrected physical quantity in KG")
    reason: str = Field(..., min_length=10, description="Documented explanation of audit adjustment")
    metadata: Optional[Dict[str, Any]] = None


class ImpactAllocationResponse(BaseModel):
    """Detailed allocation of an impact record to a credit batch."""

    id: uuid.UUID
    impact_record_id: uuid.UUID
    credit_batch_id: Optional[uuid.UUID] = None
    allocated_quantity: Decimal
    unit: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ImpactRecordResponse(BaseModel):
    """Authoritative representation of a verified physical impact outcome."""

    id: uuid.UUID
    impact_id: str
    outcome_type: ImpactOutcomeType
    status: ImpactStatus
    source_recovery_id: Optional[uuid.UUID] = None
    source_material_batch_id: Optional[uuid.UUID] = None
    source_upcycling_batch_id: Optional[uuid.UUID] = None
    verification_record_id: Optional[uuid.UUID] = None
    organization_id: uuid.UUID
    organization_name: Optional[str] = None
    program_id: Optional[uuid.UUID] = None
    program_name: Optional[str] = None
    material_type: str
    quantity: Decimal
    allocated_quantity: Decimal
    unallocated_quantity: Decimal
    unit: str
    location_name: str
    coordinates: Optional[Dict[str, float]] = None
    recorded_at: datetime
    evidence_manifest: Optional[List[Dict[str, Any]]] = None
    superseded_by_id: Optional[uuid.UUID] = None
    supersedes_id: Optional[uuid.UUID] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    allocations: List[ImpactAllocationResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 3. Eligibility Assessment Schemas
# ------------------------------------------------------------------------------

class EligibilityAssessmentCreateRequest(BaseModel):
    """Payload to initiate a credit eligibility assessment for an impact record."""

    impact_record_id: uuid.UUID
    methodology_version_id: uuid.UUID
    notes: Optional[str] = None


class EligibilityAssessmentResponse(BaseModel):
    """Reproducible assessment decision with calculation snapshot and gates."""

    id: uuid.UUID
    assessment_number: str
    impact_record_id: uuid.UUID
    impact_record_code: Optional[str] = None
    methodology_version_id: uuid.UUID
    methodology_code: Optional[str] = None
    version_tag: Optional[str] = None
    assessor_id: uuid.UUID
    assessor_name: Optional[str] = None
    status: AssessmentStatus
    gross_quantity: Decimal
    eligible_quantity: Decimal
    net_credit_units: Decimal
    validation_checklist: Dict[str, Any]
    reasons: List[str]
    calculation_snapshot: Dict[str, Any]
    is_reproducible: bool
    notes: Optional[str] = None
    assessed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
