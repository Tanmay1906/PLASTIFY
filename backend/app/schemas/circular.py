"""PLASTIFY Circular Economy Pydantic Schemas: Recycling, Upcycling, and Passports."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.circular import MaterialBatchStatus, UpcyclingBatchStatus


# ------------------------------------------------------------------------------
# 1. Incoming Verified Material for Recyclers
# ------------------------------------------------------------------------------


class IncomingMaterialResponse(BaseModel):
    """Verified raw recovery event ready to be drawn into a recycling batch."""

    recovery_id: uuid.UUID
    recovery_human_id: str
    program_id: uuid.UUID
    program_name: Optional[str] = None
    material_type: str
    collected_weight_kg: float
    delivered_weight_kg: Optional[float] = None
    verified_weight_kg: float
    already_allocated_weight_kg: float
    available_weight_kg: float
    collection_location: str
    collected_at: datetime
    delivery_code: Optional[str] = None
    destination_organization_id: Optional[uuid.UUID] = None

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 2. Recycling Batch Schemas
# ------------------------------------------------------------------------------


class MaterialBatchItemInput(BaseModel):
    """Input specification drawing verified material from a single recovery event."""

    recovery_id: uuid.UUID
    allocated_weight_kg: float = Field(..., gt=0.0, description="Weight in kg to draw from this recovery event")


class MaterialBatchCreateRequest(BaseModel):
    """Payload to initiate a new recycling processing batch."""

    material_type: str = Field(..., min_length=2, max_length=50)
    source_items: List[MaterialBatchItemInput] = Field(..., min_length=1, description="List of verified recovery events to process")
    notes: Optional[str] = None
    verification_reference: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MaterialBatchProcessingUpdateRequest(BaseModel):
    """Update processing yields, outputs, and residual waste during or after recycling."""

    recycled_output_kg: float = Field(..., ge=0.0, description="Recovered usable clean flakes/pellets output")
    residual_kg: float = Field(..., ge=0.0, description="Non-recyclable residue, contamination, or rejected scrap")
    notes: Optional[str] = None
    verification_reference: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MaterialBatchItemResponse(BaseModel):
    """Item record linking an input recovery event to a material batch."""

    id: uuid.UUID
    recovery_id: uuid.UUID
    recovery_human_id: Optional[str] = None
    allocated_weight_kg: float
    verified_weight_kg: float
    material_type: str
    collected_at: Optional[datetime] = None
    collection_location: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MaterialBatchEvidenceResponse(BaseModel):
    """Evidence file attached to a recycling batch."""

    id: uuid.UUID
    material_batch_id: uuid.UUID
    uploader_id: uuid.UUID
    uploader_name: Optional[str] = None
    evidence_type: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    sha256_hash: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialBatchResponse(BaseModel):
    """Detailed response model for an industrial recycling batch."""

    id: uuid.UUID
    batch_id: str
    recycler_organization_id: uuid.UUID
    recycler_organization_name: Optional[str] = None
    processor_id: uuid.UUID
    processor_name: Optional[str] = None
    material_type: str
    input_weight_kg: float
    recycled_output_kg: float
    residual_kg: float
    yield_percentage: float
    allocated_upcycling_weight_kg: float
    available_for_upcycling_kg: float
    processing_date: datetime
    status: MaterialBatchStatus
    verification_reference: Optional[str] = None
    material_passport_code: Optional[str] = None
    notes: Optional[str] = None
    items: List[MaterialBatchItemResponse] = Field(default_factory=list)
    evidences: List[MaterialBatchEvidenceResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialPassportResponse(BaseModel):
    """Digital Material Passport summary and provenance credentials."""

    passport_code: str
    material_batch_id: uuid.UUID
    batch_human_id: str
    material_type: str
    input_weight_kg: float
    recycled_output_kg: float
    residual_kg: float
    yield_percentage: float
    recycler_organization_name: str
    processing_date: datetime
    qr_code_identifier: str
    verification_reference: Optional[str] = None
    source_recoveries_count: int
    source_recovery_ids: List[str]
    mass_accounting: Dict[str, float]
    issued_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 3. Upcycling Engine Schemas
# ------------------------------------------------------------------------------


class AvailableRecycledMaterialResponse(BaseModel):
    """Available recycled raw material listing for circular manufacturers."""

    material_batch_id: uuid.UUID
    batch_id: str
    recycler_organization_name: str
    material_type: str
    recycled_output_kg: float
    allocated_upcycling_weight_kg: float
    available_weight_kg: float
    processing_date: datetime

    model_config = ConfigDict(from_attributes=True)


class UpcyclingAllocationInput(BaseModel):
    """Allocation from an existing completed MaterialBatch into an UpcyclingBatch."""

    material_batch_id: uuid.UUID
    allocated_weight_kg: float = Field(..., gt=0.0, description="Weight in kg to draw from this material batch")


class UpcyclingBatchCreateRequest(BaseModel):
    """Payload to initiate a new circular upcycling production batch."""

    product_type: str = Field(..., min_length=2, max_length=100)
    material_allocations: List[UpcyclingAllocationInput] = Field(..., min_length=1)
    unit_of_measure: str = Field("UNITS", min_length=1, max_length=20)
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class UpcyclingQualityUpdateRequest(BaseModel):
    """Record quality control specifications and inspection results."""

    quality_verified: bool
    quality_rating: Optional[str] = Field(None, max_length=50)
    quality_notes: Optional[str] = None


class UpcyclingBatchCompleteRequest(BaseModel):
    """Finalize upcycling production batch with completed product count."""

    quantity_produced: int = Field(..., ge=1, description="Total units of circular products created")
    notes: Optional[str] = None


class UpcyclingAllocationResponse(BaseModel):
    """Individual draw of recycled material into an upcycling batch."""

    id: uuid.UUID
    material_batch_id: uuid.UUID
    material_batch_code: str
    material_type: str
    allocated_weight_kg: float
    recycler_organization_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UpcyclingBatchEvidenceResponse(BaseModel):
    """Quality and production documentation for upcycling operations."""

    id: uuid.UUID
    upcycling_batch_id: uuid.UUID
    uploader_id: uuid.UUID
    uploader_name: Optional[str] = None
    evidence_type: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    sha256_hash: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpcyclingBatchResponse(BaseModel):
    """Detailed response for an upcycling manufacturing batch."""

    id: uuid.UUID
    batch_id: str
    upcycler_organization_id: uuid.UUID
    upcycler_organization_name: Optional[str] = None
    creator_id: uuid.UUID
    creator_name: Optional[str] = None
    product_type: str
    total_input_material_kg: float
    quantity_produced: int
    unit_of_measure: str
    quality_verified: bool
    quality_rating: Optional[str] = None
    quality_notes: Optional[str] = None
    quality_verified_at: Optional[datetime] = None
    status: UpcyclingBatchStatus
    notes: Optional[str] = None
    allocations: List[UpcyclingAllocationResponse] = Field(default_factory=list)
    evidences: List[UpcyclingBatchEvidenceResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 4. Product & Product Passport Schemas
# ------------------------------------------------------------------------------


class ProductCreateRequest(BaseModel):
    """Register finished products stemming from a completed upcycling batch."""

    name: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None
    sku: Optional[str] = Field(None, max_length=100)
    weight_per_unit_kg: Optional[float] = Field(None, gt=0.0)
    recycled_content_percentage: float = Field(100.0, ge=0.0, le=100.0)
    metadata: Optional[Dict[str, Any]] = None


class ProductResponse(BaseModel):
    """Registered circular product response."""

    id: uuid.UUID
    product_code: str
    sku: Optional[str] = None
    name: str
    description: Optional[str] = None
    product_type: str
    organization_id: uuid.UUID
    organization_name: Optional[str] = None
    upcycling_batch_id: uuid.UUID
    upcycling_batch_code: Optional[str] = None
    weight_per_unit_kg: Optional[float] = None
    recycled_content_percentage: float
    passport_id: Optional[str] = None
    qr_code_url: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MassAccountingSummary(BaseModel):
    """Strictly segregated physical mass accounting from collection to circular product."""

    collected_weight_kg: float = Field(..., description="Original raw collected weight from recovery events")
    delivered_weight_kg: float = Field(..., description="Weight delivered to recycler by logistics")
    verified_weight_kg: float = Field(..., description="Authoritative verified weight approved by human verifiers")
    recycled_output_kg: float = Field(..., description="Usable secondary flakes/pellets produced by recycling")
    upcycled_material_kg: float = Field(..., description="Secondary material consumed in this product's upcycling batch")
    residual_kg: float = Field(..., description="Rejected residue and non-recyclable process loss")
    overall_recovery_yield_pct: float = Field(..., description="(recycled_output_kg / verified_weight_kg) * 100")


class SourceRecoverySummary(BaseModel):
    """Provenance trail entry back to an original collection event."""

    recovery_id: uuid.UUID
    recovery_human_id: str
    material_type: str
    collected_weight_kg: float
    verified_weight_kg: float
    allocated_to_batch_kg: float
    collection_location: str
    collection_coordinates: Optional[Dict[str, float]] = None
    collected_at: datetime
    collector_organization_name: Optional[str] = None
    program_name: Optional[str] = None
    verification_code: Optional[str] = None


class ProductPassportProvenanceResponse(BaseModel):
    """QR-ready Digital Product Passport providing full unalterable provenance."""

    passport_id: str
    qr_ready_identifier: str
    qr_code_url: Optional[str] = None
    public_url: Optional[str] = None
    product: ProductResponse
    upcycling_batch: UpcyclingBatchResponse
    material_batches: List[MaterialBatchResponse]
    source_recoveries: List[SourceRecoverySummary]
    mass_accounting: MassAccountingSummary
    issued_at: datetime

    model_config = ConfigDict(from_attributes=True)
