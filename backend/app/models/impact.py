"""PLASTIFY Impact Ledger and Methodology Models.

Entities:
- ImpactOutcomeType: Discrete physical outcome classifications (collection, delivery, recycling, etc.)
- ImpactStatus: Lifecycle state of an impact record (VERIFIED, ALLOCATED, SUPERSEDED, REVOKED)
- ImpactRecord: Authoritative provenance-linked impact outcome record
- ImpactAllocation: Commitment of verified physical impact to downstream credit batches
- Methodology: High-level standard or protocol definition
- MethodologyVersion: Immutable versioned rules, credit factors, and calculation logic
- AssessmentStatus: Eligibility assessment determinations
- EligibilityAssessment: Reproducible credit eligibility evaluation snapshot
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.circular import MaterialBatch, UpcyclingBatch
    from app.models.credit import CreditBatch
    from app.models.organization import Organization
    from app.models.program import Program
    from app.models.recovery import RecoveryEvent
    from app.models.user import User
    from app.models.verification import VerificationRecord


class ImpactOutcomeType(str, Enum):
    """Authoritative physical circular economy outcome classifications."""

    COLLECTION = "COLLECTION"                     # Verified recovery from natural environment / waste stream
    DELIVERY = "DELIVERY"                         # Custody delivery accepted at processing facility
    RECYCLING_INPUT = "RECYCLING_INPUT"           # Verified physical material fed into industrial recycling
    RECYCLED_OUTPUT = "RECYCLED_OUTPUT"           # Certified secondary raw polymer produced (flake/pellet)
    UPCYCLED_PRODUCT = "UPCYCLED_PRODUCT"         # Durable circular product manufactured
    RESIDUE = "RESIDUE"                           # Unrecoverable processing residual / waste fraction


class ImpactStatus(str, Enum):
    """Lifecycle state of an auditable impact record."""

    VERIFIED = "VERIFIED"         # Authoritative verified impact, ready for assessment/allocation
    ALLOCATED = "ALLOCATED"       # Fully committed to downstream credit issuance
    SUPERSEDED = "SUPERSEDED"     # Traceably replaced by an amended impact record
    REVOKED = "REVOKED"           # Invalidated due to audit discrepancy or fraud finding


class AssessmentStatus(str, Enum):
    """Determination of credit eligibility assessment."""

    ELIGIBLE = "ELIGIBLE"                 # Meets all criteria and evidence thresholds
    INELIGIBLE = "INELIGIBLE"             # Fails baseline, additionality, or verification gates
    REQUIRES_REVIEW = "REQUIRES_REVIEW"   # Missing non-critical evidence or flagged by Sentinel


# ------------------------------------------------------------------------------
# 1. Methodology & Immutable Versions
# ------------------------------------------------------------------------------

class Methodology(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Accounting methodology or standard protocol definition."""

    __tablename__ = "methodologies"

    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    standard_name: Mapped[str] = mapped_column(
        String(150), nullable=False, default="PLASTIFY Environmental Protocol"
    )
    is_standard_recognized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    registry_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    versions: Mapped[List["MethodologyVersion"]] = relationship(
        "MethodologyVersion",
        back_populates="methodology",
        cascade="all, delete-orphan",
        order_by="MethodologyVersion.created_at.asc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Methodology(code='{self.code}', name='{self.name}')>"


class MethodologyVersion(Base, UUIDPrimaryKeyMixin):
    """Immutable versioned specification of accounting rules, factors, and gates."""

    __tablename__ = "methodology_versions"
    __table_args__ = (
        UniqueConstraint("methodology_id", "version_tag", name="uq_methodology_version_tag"),
    )

    methodology_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("methodologies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_tag: Mapped[str] = mapped_column(String(50), nullable=False)
    activity_type: Mapped[ImpactOutcomeType] = mapped_column(
        SQLEnum(ImpactOutcomeType, name="impact_outcome_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_immutable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Eligibility & Conversion Rules
    eligible_materials: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    credit_conversion_factor: Mapped[Decimal] = mapped_column(
        Numeric(12, 6, asdecimal=True), nullable=False, default=Decimal("0.001000")
    )  # e.g., 0.001 credits per 1.000 KG (i.e. 1 Credit = 1000 KG / 1 MT), or 1.0 per KG
    credit_unit_name: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PLASTIC_RECOVERY_CREDIT"
    )

    # Deduction & Discount Parameters
    additionality_discount: Mapped[Decimal] = mapped_column(
        Numeric(8, 4, asdecimal=True), nullable=False, default=Decimal("0.0000")
    )
    baseline_discount: Mapped[Decimal] = mapped_column(
        Numeric(8, 4, asdecimal=True), nullable=False, default=Decimal("0.0000")
    )
    leakage_deduction: Mapped[Decimal] = mapped_column(
        Numeric(8, 4, asdecimal=True), nullable=False, default=Decimal("0.0000")
    )

    # Gate Requirements
    required_evidence_types: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    requires_independent_verification: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    calculation_formula: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="NET = GROSS_KG * CONVERSION_FACTOR * (1 - (ADDITIONALITY + BASELINE + LEAKAGE))",
    )
    disclaimer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "DISCLAIMER: PLASTIFY impact assessments quantify verifiable physical material movements. "
            "Unless explicitly certified by a recognized sovereign or independent crediting standard body, "
            "these calculations represent auditable private environmental accounting rather than sovereign certificates."
        ),
    )
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    methodology: Mapped["Methodology"] = relationship("Methodology", back_populates="versions", lazy="selectin")
    assessments: Mapped[List["EligibilityAssessment"]] = relationship(
        "EligibilityAssessment", back_populates="methodology_version", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<MethodologyVersion(tag='{self.version_tag}', activity='{self.activity_type}')>"


# ------------------------------------------------------------------------------
# 2. Impact Records & Allocations
# ------------------------------------------------------------------------------

class ImpactRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authoritative physical outcome record anchored to verified source chains."""

    __tablename__ = "impact_records"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_impact_record_quantity_positive"),
        CheckConstraint("allocated_quantity >= 0", name="chk_impact_record_allocated_non_negative"),
        CheckConstraint("allocated_quantity <= quantity", name="chk_impact_record_allocated_lte_quantity"),
    )

    # Immutable human-readable identifier (e.g. IMP-2026-COL-000001)
    impact_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    outcome_type: Mapped[ImpactOutcomeType] = mapped_column(
        SQLEnum(ImpactOutcomeType, name="impact_outcome_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    status: Mapped[ImpactStatus] = mapped_column(
        SQLEnum(ImpactStatus, name="impact_status_enum", native_enum=False),
        nullable=False,
        default=ImpactStatus.VERIFIED,
        index=True,
    )

    # Provenance anchors to physical source records
    source_recovery_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_material_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("material_batches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_upcycling_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("upcycling_batches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    verification_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("verification_records.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    program_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Exact physical accounting
    material_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    allocated_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False, default=Decimal("0.0000")
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="KG")

    # Spatial and Temporal metadata
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    coordinates: Mapped[Optional[Dict[str, float]]] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Immutability, evidence manifest, and amendment audit trail
    evidence_manifest: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("impact_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("impact_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[organization_id], lazy="selectin"
    )
    program: Mapped[Optional["Program"]] = relationship(
        "Program", foreign_keys=[program_id], lazy="selectin"
    )
    source_recovery: Mapped[Optional["RecoveryEvent"]] = relationship(
        "RecoveryEvent", foreign_keys=[source_recovery_id], lazy="selectin"
    )
    source_material_batch: Mapped[Optional["MaterialBatch"]] = relationship(
        "MaterialBatch", foreign_keys=[source_material_batch_id], lazy="selectin"
    )
    source_upcycling_batch: Mapped[Optional["UpcyclingBatch"]] = relationship(
        "UpcyclingBatch", foreign_keys=[source_upcycling_batch_id], lazy="selectin"
    )
    verification_record: Mapped[Optional["VerificationRecord"]] = relationship(
        "VerificationRecord", foreign_keys=[verification_record_id], lazy="selectin"
    )
    allocations: Mapped[List["ImpactAllocation"]] = relationship(
        "ImpactAllocation",
        back_populates="impact_record",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    assessments: Mapped[List["EligibilityAssessment"]] = relationship(
        "EligibilityAssessment",
        back_populates="impact_record",
        lazy="selectin",
    )

    @property
    def unallocated_quantity(self) -> Decimal:
        """Available unallocated physical quantity remaining."""
        return max(Decimal("0.0000"), self.quantity - self.allocated_quantity)

    def __repr__(self) -> str:
        return f"<ImpactRecord(id='{self.impact_id}', type='{self.outcome_type}', qty={self.quantity}{self.unit})>"


class ImpactAllocation(Base, UUIDPrimaryKeyMixin):
    """Traceable allocation of physical impact quantity to a specific credit batch."""

    __tablename__ = "impact_allocations"
    __table_args__ = (
        CheckConstraint("allocated_quantity > 0", name="chk_impact_alloc_quantity_positive"),
    )

    impact_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("impact_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credit_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("credit_batches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    allocated_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="KG")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    impact_record: Mapped["ImpactRecord"] = relationship(
        "ImpactRecord", back_populates="allocations", lazy="selectin"
    )
    credit_batch: Mapped[Optional["CreditBatch"]] = relationship(
        "CreditBatch", back_populates="impact_allocations", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<ImpactAllocation(impact='{self.impact_record_id}', qty={self.allocated_quantity}{self.unit})>"


# ------------------------------------------------------------------------------
# 3. Eligibility Assessment
# ------------------------------------------------------------------------------

class EligibilityAssessment(Base, UUIDPrimaryKeyMixin):
    """Reproducible evaluation snapshot of an ImpactRecord against a MethodologyVersion."""

    __tablename__ = "eligibility_assessments"
    __table_args__ = (
        CheckConstraint("gross_quantity >= 0", name="chk_assessment_gross_non_neg"),
        CheckConstraint("eligible_quantity >= 0", name="chk_assessment_eligible_non_neg"),
        CheckConstraint("net_credit_units >= 0", name="chk_assessment_net_credits_non_neg"),
    )

    assessment_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    impact_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("impact_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    methodology_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("methodology_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        SQLEnum(AssessmentStatus, name="assessment_status_enum", native_enum=False),
        nullable=False,
        index=True,
    )

    # Exact calculated figures
    gross_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    eligible_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    net_credit_units: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )

    # Reproducibility Snapshot
    validation_checklist: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    reasons: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    calculation_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_reproducible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    impact_record: Mapped["ImpactRecord"] = relationship(
        "ImpactRecord", back_populates="assessments", lazy="selectin"
    )
    methodology_version: Mapped["MethodologyVersion"] = relationship(
        "MethodologyVersion", back_populates="assessments", lazy="selectin"
    )
    assessor: Mapped["User"] = relationship("User", foreign_keys=[assessor_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<EligibilityAssessment(num='{self.assessment_number}', status='{self.status}', net={self.net_credit_units})>"
