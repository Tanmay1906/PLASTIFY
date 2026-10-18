"""PLASTIFY Verification Engine Models.

Authoritative verification records, audit findings, and queue entities.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.recovery import RecoveryEvent
    from app.models.user import User


class VerificationDecision(str, Enum):
    """Authoritative verifier determination."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"


class FindingSeverity(str, Enum):
    """Impact level of a verification discrepancy or observation."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class FindingCategory(str, Enum):
    """Categorization of audit findings."""

    WEIGHT_DISCREPANCY = "WEIGHT_DISCREPANCY"
    EVIDENCE_INTEGRITY = "EVIDENCE_INTEGRITY"
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    TIMELINE_ANOMALY = "TIMELINE_ANOMALY"
    DOCUMENTATION = "DOCUMENTATION"
    MATERIAL_MISMATCH = "MATERIAL_MISMATCH"
    SENTINEL_FLAG = "SENTINEL_FLAG"
    OTHER = "OTHER"


class VerificationRecord(Base, UUIDPrimaryKeyMixin):
    """Immutable audit determination registered by an authorized verifier."""

    __tablename__ = "verification_records"

    # Unique human-readable code: VRF-2026-XXXXXXXX
    verification_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    verifier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    verifier_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    decision: Mapped[VerificationDecision] = mapped_column(
        SQLEnum(VerificationDecision, name="verification_decision_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    verified_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Immutable creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship(
        "RecoveryEvent", back_populates="verification_records", lazy="selectin"
    )
    verifier: Mapped["User"] = relationship(
        "User", foreign_keys=[verifier_id], lazy="selectin"
    )
    verifier_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[verifier_organization_id], lazy="selectin"
    )
    findings: Mapped[List["VerificationFinding"]] = relationship(
        "VerificationFinding",
        back_populates="verification_record",
        cascade="all, delete-orphan",
        order_by="VerificationFinding.created_at.asc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<VerificationRecord(code='{self.verification_code}', decision='{self.decision}')>"


class VerificationFinding(Base, UUIDPrimaryKeyMixin):
    """Specific observation, automated Sentinel flag, or discrepancy detected during review."""

    __tablename__ = "verification_findings"

    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("verification_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    finder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        SQLEnum(FindingSeverity, name="finding_severity_enum", native_enum=False),
        nullable=False,
        default=FindingSeverity.WARNING,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    is_resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship(
        "RecoveryEvent", back_populates="verification_findings", lazy="selectin"
    )
    verification_record: Mapped[Optional["VerificationRecord"]] = relationship(
        "VerificationRecord", back_populates="findings", lazy="selectin"
    )
    finder: Mapped["User"] = relationship(
        "User", foreign_keys=[finder_id], lazy="selectin"
    )
    resolved_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[resolved_by_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<VerificationFinding(id={self.id}, severity='{self.severity}', category='{self.category}')>"
