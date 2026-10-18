"""PLASTIFY Logistics and Delivery Pydantic Schemas.

Defines input payloads and response contracts for:
- Pickup assignments and carrier acceptance
- Physical movement tracking (pickup, in-transit, delivery)
- Recycler receipt confirmation and configurable weight tolerance verification
- Delivery evidence and audit history
"""

from datetime import datetime
from typing import List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.logistics import (
    AssignmentStatus,
    DeliveryStatus,
    WeightToleranceStatus,
)
from app.schemas.custody import CustodyEventResponse


# ==============================================================================
# Request Schemas
# ==============================================================================


class AssignLogisticsRequest(BaseModel):
    """Payload to assign a submitted recovery event to a logistics carrier."""

    recovery_id: uuid.UUID = Field(
        ..., description="Unique ID of the recovered plastic batch ready for transport"
    )
    logistics_organization_id: uuid.UUID = Field(
        ..., description="Target logistics partner organization ID"
    )
    destination_organization_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Target destination recycling or upcycling organization ID",
    )
    destination_location: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Delivery destination facility name or address",
    )
    scheduled_pickup_date: Optional[datetime] = Field(
        default=None, description="Scheduled or requested pickup timestamp"
    )
    notes: Optional[str] = Field(
        default=None, description="Handling instructions or route notes"
    )


class AcceptAssignmentRequest(BaseModel):
    """Payload for logistics carrier to acknowledge and accept transport assignment."""

    assigned_to_driver_id: Optional[uuid.UUID] = Field(
        default=None, description="Designated courier/driver user ID within logistics org"
    )
    notes: Optional[str] = Field(
        default=None, description="Acceptance remarks or operational notes"
    )


class MarkPickupRequest(BaseModel):
    """Payload to record completed physical collection from collector."""

    pickup_timestamp: Optional[datetime] = Field(
        default=None, description="Actual physical pickup timestamp (defaults to current UTC)"
    )
    vehicle_number: Optional[str] = Field(
        default=None, max_length=100, description="Transport vehicle registration / license plate"
    )
    driver_id: Optional[uuid.UUID] = Field(
        default=None, description="Driver or field operator who completed pickup"
    )
    notes: Optional[str] = Field(
        default=None, description="Observations at pickup point (e.g. bale condition)"
    )


class MarkInTransitRequest(BaseModel):
    """Payload to record material batch currently in transit."""

    tracking_number: Optional[str] = Field(
        default=None, max_length=100, description="Carrier consignment or GPS tracking tag"
    )
    in_transit_timestamp: Optional[datetime] = Field(
        default=None, description="Departure or departure confirmation timestamp"
    )
    current_location: Optional[str] = Field(
        default=None, max_length=255, description="Transit hub or departure checkpoint"
    )
    notes: Optional[str] = Field(
        default=None, description="In-transit tracking notes or route updates"
    )


class MarkDeliveredRequest(BaseModel):
    """Payload for logistics carrier marking physical arrival and drop-off."""

    delivered_weight_kg: Optional[float] = Field(
        default=None,
        gt=0,
        description="Gross/net delivered weight measured by logistics on drop-off",
    )
    delivery_timestamp: Optional[datetime] = Field(
        default=None, description="Timestamp of physical delivery at recipient facility"
    )
    notes: Optional[str] = Field(
        default=None, description="Delivery handover observations or gate entry note"
    )
    evidence_ids: Optional[List[uuid.UUID]] = Field(
        default=None, description="Existing evidence IDs to associate (waybill, gate pass)"
    )


class RecyclerConfirmReceiptRequest(BaseModel):
    """Payload for receiving recycling facility to confirm delivery and weigh shipment."""

    received_weight_kg: float = Field(
        ..., gt=0, description="Certified weighbridge / scale weight in kilograms upon receipt"
    )
    received_timestamp: Optional[datetime] = Field(
        default=None, description="Handover / intake weigh timestamp"
    )
    receipt_notes: Optional[str] = Field(
        default=None, description="Receiving inspection notes, contamination check, moisture observation"
    )
    evidence_ids: Optional[List[uuid.UUID]] = Field(
        default=None, description="Evidence IDs for scale ticket or intake photo"
    )


# ==============================================================================
# Response Schemas
# ==============================================================================


class DeliveryEvidenceResponse(BaseModel):
    """Metadata for digital proof attached to a physical delivery."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivery_id: uuid.UUID
    evidence_id: Optional[uuid.UUID] = None
    uploader_id: uuid.UUID
    uploader_name: Optional[str] = None
    evidence_type: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    sha256_hash: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class DeliveryResponse(BaseModel):
    """Complete public representation of a material delivery record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivery_code: str
    assignment_id: uuid.UUID
    recovery_id: uuid.UUID
    recovery_human_id: Optional[str] = None
    logistics_organization_id: uuid.UUID
    logistics_organization_name: Optional[str] = None
    recycler_organization_id: Optional[uuid.UUID] = None
    recycler_organization_name: Optional[str] = None
    driver_id: Optional[uuid.UUID] = None
    driver_name: Optional[str] = None
    receiver_id: Optional[uuid.UUID] = None
    receiver_name: Optional[str] = None
    status: DeliveryStatus

    # Weight tracking & tolerance verification
    expected_weight_kg: float
    delivered_weight_kg: Optional[float] = None
    received_weight_kg: Optional[float] = None
    weight_discrepancy_kg: Optional[float] = None
    weight_tolerance_pct: float
    weight_tolerance_status: WeightToleranceStatus

    # Milestones
    pickup_timestamp: Optional[datetime] = None
    in_transit_timestamp: Optional[datetime] = None
    delivery_timestamp: Optional[datetime] = None
    received_timestamp: Optional[datetime] = None

    # Metadata & Notes
    vehicle_number: Optional[str] = None
    tracking_number: Optional[str] = None
    notes: Optional[str] = None
    receipt_notes: Optional[str] = None
    evidence_records: List[DeliveryEvidenceResponse] = Field(default_factory=list)

    created_at: datetime
    updated_at: Optional[datetime] = None


class LogisticsAssignmentResponse(BaseModel):
    """Public representation of a logistics carrier transport assignment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assignment_code: str
    recovery_id: uuid.UUID
    recovery_human_id: Optional[str] = None
    program_id: uuid.UUID
    program_name: Optional[str] = None
    logistics_organization_id: uuid.UUID
    logistics_organization_name: Optional[str] = None
    destination_organization_id: Optional[uuid.UUID] = None
    destination_organization_name: Optional[str] = None
    assigned_by_id: uuid.UUID
    assigned_by_name: Optional[str] = None
    assigned_to_driver_id: Optional[uuid.UUID] = None
    assigned_to_driver_name: Optional[str] = None
    status: AssignmentStatus
    pickup_location: str
    destination_location: Optional[str] = None
    scheduled_pickup_date: Optional[datetime] = None
    expected_weight_kg: float
    notes: Optional[str] = None
    delivery: Optional[DeliveryResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class DeliveryHistoryResponse(BaseModel):
    """Complete delivery history with immutable chain-of-custody audit trail."""

    delivery: DeliveryResponse
    custody_events: List[CustodyEventResponse] = Field(default_factory=list)
