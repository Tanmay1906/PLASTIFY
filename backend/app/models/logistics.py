"""PLASTIFY Logistics and Delivery Engine Models.

Entities:
- LogisticsAssignment: Assigns a recovery event to a logistics partner for transport.
- Delivery: Tracks physical transit, pickup/delivery milestones, expected vs delivered weights,
  and tolerance evaluation upon recycler receipt.
- DeliveryEvidence: Associates delivery proofs (waybills, weighbridge tickets, photo evidence) with a delivery.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
import uuid
from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evidence import Evidence
    from app.models.organization import Organization
    from app.models.program import Program
    from app.models.recovery import RecoveryEvent
    from app.models.user import User


class AssignmentStatus(str, Enum):
    """Lifecycle status of a logistics transport assignment."""

    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    """Lifecycle status of a physical plastic material delivery."""

    PENDING = "PENDING"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class WeightToleranceStatus(str, Enum):
    """Weight discrepancy evaluation result upon receipt."""

    PENDING = "PENDING"
    PASS = "PASS"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"


class LogisticsAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Assignment linking a recovery event to a certified logistics carrier."""

    __tablename__ = "logistics_assignments"

    assignment_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logistics_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    destination_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    assigned_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_to_driver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        SQLEnum(AssignmentStatus, name="assignment_status_enum", native_enum=False),
        nullable=False,
        default=AssignmentStatus.ASSIGNED,
        index=True,
    )
    pickup_location: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scheduled_pickup_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship("RecoveryEvent", lazy="selectin")
    program: Mapped["Program"] = relationship("Program", lazy="selectin")
    logistics_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[logistics_organization_id], lazy="selectin"
    )
    destination_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[destination_organization_id], lazy="selectin"
    )
    assigned_by: Mapped["User"] = relationship(
        "User", foreign_keys=[assigned_by_id], lazy="selectin"
    )
    assigned_to_driver: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_to_driver_id], lazy="selectin"
    )
    delivery: Mapped[Optional["Delivery"]] = relationship(
        "Delivery", back_populates="assignment", uselist=False, lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<LogisticsAssignment(code='{self.assignment_code}', status='{self.status}')>"


class Delivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Physical delivery record tracking movement, weights, and confirmation."""

    __tablename__ = "deliveries"

    delivery_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("logistics_assignments.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logistics_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recycler_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    driver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    receiver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        SQLEnum(DeliveryStatus, name="delivery_status_enum", native_enum=False),
        nullable=False,
        default=DeliveryStatus.PENDING,
        index=True,
    )

    # Weight tracking & tolerance verification
    expected_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    delivered_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    received_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_discrepancy_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    weight_tolerance_status: Mapped[WeightToleranceStatus] = mapped_column(
        SQLEnum(
            WeightToleranceStatus,
            name="weight_tolerance_status_enum",
            native_enum=False,
        ),
        nullable=False,
        default=WeightToleranceStatus.PENDING,
        index=True,
    )

    # Milestones timestamps
    pickup_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    in_transit_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Metadata & Notes
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    assignment: Mapped["LogisticsAssignment"] = relationship(
        "LogisticsAssignment", back_populates="delivery", lazy="selectin"
    )
    recovery: Mapped["RecoveryEvent"] = relationship("RecoveryEvent", lazy="selectin")
    logistics_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[logistics_organization_id], lazy="selectin"
    )
    recycler_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[recycler_organization_id], lazy="selectin"
    )
    driver: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[driver_id], lazy="selectin"
    )
    receiver: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[receiver_id], lazy="selectin"
    )
    evidence_records: Mapped[List["DeliveryEvidence"]] = relationship(
        "DeliveryEvidence",
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="DeliveryEvidence.created_at.asc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Delivery(code='{self.delivery_code}', status='{self.status}')>"


class DeliveryEvidence(Base, UUIDPrimaryKeyMixin):
    """Digital proof of delivery, weigh slips, and handover documentation."""

    __tablename__ = "delivery_evidences"

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="DELIVERY_PROOF", index=True
    )
    storage_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    delivery: Mapped["Delivery"] = relationship(
        "Delivery", back_populates="evidence_records", lazy="selectin"
    )
    uploader: Mapped["User"] = relationship("User", lazy="selectin")
    evidence: Mapped[Optional["Evidence"]] = relationship("Evidence", lazy="selectin")

    def __repr__(self) -> str:
        return f"<DeliveryEvidence(id={self.id}, type='{self.evidence_type}')>"
