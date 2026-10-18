"""PLASTIFY Plastic Collection and Recovery Event Models."""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evidence import Evidence
    from app.models.organization import Organization
    from app.models.program import Program
    from app.models.sentinel import SentinelResult
    from app.models.user import User
    from app.models.verification import VerificationFinding, VerificationRecord


class RecoveryStatus(str, Enum):
    """Lifecycle states of a plastic recovery event."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FLAGGED = "FLAGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RecoveryEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Auditable primary record of post-consumer plastic collection/recovery."""

    __tablename__ = "recovery_events"

    # Official immutable human-readable identifier (e.g. POP-DEL-2026-000184)
    recovery_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    collector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    collector_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    material_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    collection_location: Mapped[str] = mapped_column(String(255), nullable=False)
    collection_coordinates: Mapped[Optional[Dict[str, float]]] = mapped_column(
        JSON, nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[RecoveryStatus] = mapped_column(
        SQLEnum(RecoveryStatus, name="recovery_status_enum", native_enum=False),
        nullable=False,
        default=RecoveryStatus.DRAFT,
        index=True,
    )
    custody_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="CREATED", index=True
    )

    # Relationships
    program: Mapped["Program"] = relationship("Program", back_populates="recoveries", lazy="selectin")
    collector: Mapped["User"] = relationship("User", foreign_keys=[collector_id], lazy="selectin")
    collector_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[collector_organization_id], lazy="selectin"
    )
    history: Mapped[List["RecoveryEventHistory"]] = relationship(
        "RecoveryEventHistory",
        back_populates="recovery",
        cascade="all, delete-orphan",
        order_by="RecoveryEventHistory.created_at.asc()",
        lazy="selectin",
    )
    evidence: Mapped[List["Evidence"]] = relationship(
        "Evidence",
        back_populates="recovery",
        cascade="all, delete-orphan",
        order_by="Evidence.created_at.asc()",
        lazy="selectin",
    )
    verification_records: Mapped[List["VerificationRecord"]] = relationship(
        "VerificationRecord",
        back_populates="recovery",
        cascade="all, delete-orphan",
        order_by="VerificationRecord.created_at.desc()",
        lazy="selectin",
    )
    verification_findings: Mapped[List["VerificationFinding"]] = relationship(
        "VerificationFinding",
        back_populates="recovery",
        cascade="all, delete-orphan",
        order_by="VerificationFinding.created_at.asc()",
        lazy="selectin",
    )
    sentinel_result: Mapped[Optional["SentinelResult"]] = relationship(
        "SentinelResult",
        back_populates="recovery",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<RecoveryEvent(id={self.id}, recovery_id='{self.recovery_id}', status='{self.status}')>"


class RecoveryEventHistory(Base, UUIDPrimaryKeyMixin):
    """Immutable state transition audit record for recovery events."""

    __tablename__ = "recovery_event_histories"

    recovery_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship("RecoveryEvent", back_populates="history")
    actor: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return f"<RecoveryEventHistory(event_id={self.recovery_event_id}, {self.from_status} -> {self.to_status})>"


class RecoverySequence(Base):
    """Atomic monotonic sequence counter for human-readable Recovery IDs."""

    __tablename__ = "recovery_sequences"

    prefix: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<RecoverySequence(prefix='{self.prefix}', seq={self.last_sequence})>"
