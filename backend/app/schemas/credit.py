"""PLASTIFY Plastic Credit, Issuance, Transaction, and Retirement Pydantic Schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.credit import CreditBatchStatus, CreditStatus, TransactionType


# ------------------------------------------------------------------------------
# 1. Credit Batch Schemas
# ------------------------------------------------------------------------------

class AssessedImpactAllocationInput(BaseModel):
    """Specification of an assessed eligible impact record and weight to draw into the credit batch."""

    assessment_id: uuid.UUID
    allocated_quantity_kg: Decimal = Field(..., gt=0, description="Quantity in KG of assessed eligible material to allocate")


class CreditBatchCreateRequest(BaseModel):
    """Payload to assemble eligible assessed impacts into a formal credit batch."""

    methodology_version_id: uuid.UUID
    allocations: List[AssessedImpactAllocationInput] = Field(..., min_length=1, description="List of assessed impacts to include")
    vintage_year: int = Field(default=2026, ge=2020, le=2050)
    credit_type: str = Field(default="PLASTIC_RECOVERY_CREDIT", max_length=50)
    registry_name: Optional[str] = Field(default="PLASTIFY_INTERNAL_REGISTRY", max_length=100)
    notes: Optional[str] = None


class CreditBatchApproveRequest(BaseModel):
    """Payload for authoritative verifier/admin to approve a credit batch for issuance."""

    notes: Optional[str] = None


class CreditBatchIssueRequest(BaseModel):
    """Payload to execute controlled credit issuance and mint serials."""

    idempotency_key: str = Field(..., min_length=8, max_length=100, description="Unique client key preventing double-issuance on retry")
    issuance_notes: Optional[str] = None
    simulate_registry_timeout: bool = Field(default=False, description="Test hook for simulating external registry unavailability")


class PlasticCreditResponse(BaseModel):
    """Serialized plastic credit tranche."""

    id: uuid.UUID
    credit_batch_id: uuid.UUID
    serial_number: str
    serial_start: int
    serial_end: int
    quantity: Decimal
    owner_organization_id: uuid.UUID
    owner_organization_name: Optional[str] = None
    status: CreditStatus
    vintage_year: int
    credit_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreditBatchResponse(BaseModel):
    """Public representation of an auditable credit issuance batch."""

    id: uuid.UUID
    batch_number: str
    organization_id: uuid.UUID
    organization_name: Optional[str] = None
    methodology_version_id: uuid.UUID
    methodology_code: Optional[str] = None
    version_tag: Optional[str] = None
    creator_id: uuid.UUID
    creator_name: Optional[str] = None
    approver_id: Optional[uuid.UUID] = None
    approver_name: Optional[str] = None
    issuer_id: Optional[uuid.UUID] = None
    issuer_name: Optional[str] = None
    total_credits: Decimal
    available_credits: Decimal
    retired_credits: Decimal
    credit_type: str
    vintage_year: int
    status: CreditBatchStatus
    registry_name: str
    registry_batch_id: Optional[str] = None
    registry_status: str
    is_mock_issuance: bool
    idempotency_key: Optional[str] = None
    issuance_notes: Optional[str] = None
    issued_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    credits: List[PlasticCreditResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 2. Credit Transfer and Transaction Schemas
# ------------------------------------------------------------------------------

class CreditTransferRequest(BaseModel):
    """Payload to transfer active credit tranches to another organization."""

    credit_id: uuid.UUID
    to_organization_id: uuid.UUID
    quantity: Optional[Decimal] = Field(default=None, gt=0, description="Optional partial transfer quantity")
    idempotency_key: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None


class CreditTransactionResponse(BaseModel):
    """Immutable transaction audit log entry."""

    id: uuid.UUID
    transaction_id: str
    credit_batch_id: uuid.UUID
    credit_id: Optional[uuid.UUID] = None
    tx_type: TransactionType
    quantity: Decimal
    from_organization_id: Optional[uuid.UUID] = None
    from_organization_name: Optional[str] = None
    to_organization_id: Optional[uuid.UUID] = None
    to_organization_name: Optional[str] = None
    actor_id: uuid.UUID
    actor_email: Optional[str] = None
    notes: Optional[str] = None
    audit_hash: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------------
# 3. Credit Retirement Schemas
# ------------------------------------------------------------------------------

class CreditRetirementRequest(BaseModel):
    """Payload to terminally retire credits on behalf of a beneficiary."""

    credit_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0, description="Amount of credits to retire")
    beneficiary_name: str = Field(..., min_length=2, max_length=255, description="Beneficiary entity claiming ecological impact")
    retirement_reason: str = Field(..., min_length=5, description="Public justification (e.g. Scope 3 Plastic Footprint Offset 2026)")
    idempotency_key: Optional[str] = Field(default=None, max_length=100, description="Client key preventing duplicate retirement on timeout")


class CreditRetirementResponse(BaseModel):
    """Authoritative retirement certificate record."""

    id: uuid.UUID
    retirement_id: str
    credit_batch_id: uuid.UUID
    credit_id: Optional[uuid.UUID] = None
    retiring_organization_id: uuid.UUID
    retiring_organization_name: Optional[str] = None
    actor_id: uuid.UUID
    actor_email: Optional[str] = None
    quantity: Decimal
    beneficiary_name: str
    retirement_reason: str
    certificate_id: str
    certificate_hash: str
    idempotency_key: Optional[str] = None
    retired_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
