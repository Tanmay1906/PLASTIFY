"""PLASTIFY Verification Engine Schemas.

Pydantic v2 schemas for verification queue, audit packages, determination actions, and findings.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from app.models.recovery import RecoveryStatus
from app.models.verification import (
    FindingCategory,
    FindingSeverity,
    VerificationDecision,
)
from app.schemas.custody import CustodyEventResponse
from app.schemas.evidence import EvidenceResponse
from app.schemas.logistics import (
    DeliveryEvidenceResponse,
    DeliveryResponse,
    LogisticsAssignmentResponse,
)
from app.schemas.recovery import RecoveryResponse


class VerificationQueueItemResponse(BaseModel):
    """Summarized recovery event waiting in the verification queue."""

    recovery_id: uuid.UUID
    recovery_human_id: str
    program_id: uuid.UUID
    program_name: str
    collector_organization_id: uuid.UUID
    collector_organization_name: str
    recycler_organization_id: Optional[uuid.UUID] = None
    recycler_organization_name: Optional[str] = None
    material_type: str
    weight_kg: float
    collected_at: datetime
    collection_location: str
    custody_status: str
    recovery_status: RecoveryStatus
    weight_tolerance_status: Optional[str] = None
    has_critical_findings: bool = False
    findings_count: int = 0
    queued_at: datetime


class VerificationFindingCreateRequest(BaseModel):
    """Register an audit discrepancy or Sentinel flag."""

    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)
    severity: FindingSeverity = FindingSeverity.WARNING
    category: FindingCategory = FindingCategory.OTHER


class VerificationFindingResolveRequest(BaseModel):
    """Mark an audit finding as resolved."""

    resolution_notes: str = Field(..., min_length=3)


class VerificationFindingResponse(BaseModel):
    """Detailed audit finding representation."""

    id: uuid.UUID
    recovery_id: uuid.UUID
    verification_record_id: Optional[uuid.UUID] = None
    finder_id: uuid.UUID
    finder_name: Optional[str] = None
    severity: FindingSeverity
    category: str
    title: str
    description: str
    is_resolved: bool
    resolution_notes: Optional[str] = None
    resolved_by_id: Optional[uuid.UUID] = None
    resolved_by_name: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime


class ApproveVerificationRequest(BaseModel):
    """Payload to grant authoritative verification approval."""

    verified_weight_kg: Optional[float] = Field(
        None, gt=0, description="Override or verified weight in kg (defaults to received weight)"
    )
    checklist: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Checklist audit results (e.g. photo_verified, weight_matched, gps_valid)",
    )
    notes: Optional[str] = None


class RejectVerificationRequest(BaseModel):
    """Payload to reject verification (reason mandatory)."""

    reason: str = Field(..., min_length=3, description="Mandatory authoritative rejection rationale")
    notes: Optional[str] = None


class FlagVerificationRequest(BaseModel):
    """Payload to request additional review or flag discrepancies (reason mandatory)."""

    reason: str = Field(..., min_length=3, description="Mandatory review request rationale")
    severity: FindingSeverity = FindingSeverity.WARNING
    category: FindingCategory = FindingCategory.SENTINEL_FLAG
    notes: Optional[str] = None


class VerificationRecordResponse(BaseModel):
    """Authoritative immutable verification record representation."""

    id: uuid.UUID
    verification_code: str
    recovery_id: uuid.UUID
    recovery_human_id: Optional[str] = None
    verifier_id: uuid.UUID
    verifier_name: Optional[str] = None
    verifier_organization_id: uuid.UUID
    verifier_organization_name: Optional[str] = None
    decision: VerificationDecision
    verified_weight_kg: Optional[float] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    checklist: Optional[Dict[str, Any]] = None
    created_at: datetime
    findings: List[VerificationFindingResponse] = []


class WeightComparisonSummary(BaseModel):
    """Expected vs delivered vs received weight reconciliation."""

    expected_weight_kg: float
    delivered_weight_kg: Optional[float] = None
    received_weight_kg: Optional[float] = None
    discrepancy_kg: Optional[float] = None
    discrepancy_pct: Optional[float] = None
    tolerance_pct: float = 2.0
    tolerance_status: Optional[str] = None


class VerificationPackageResponse(BaseModel):
    """Complete comprehensive verification dossier for human review."""

    recovery: RecoveryResponse
    collection_evidence: List[EvidenceResponse]
    logistics_assignment: Optional[LogisticsAssignmentResponse] = None
    delivery: Optional[DeliveryResponse] = None
    delivery_evidence: List[DeliveryEvidenceResponse] = []
    weight_comparison: WeightComparisonSummary
    custody_timeline: List[CustodyEventResponse]
    sentinel_findings: List[VerificationFindingResponse] = []
    sentinel_result: Optional[Any] = None
    existing_records: List[VerificationRecordResponse] = []
