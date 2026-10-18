"""PLASTIFY Corporate Plastic Recovery Program Models."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.recovery import RecoveryEvent


class ProgramStatus(str, Enum):
    """Lifecycle states of a corporate plastic recovery program."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlasticMaterialType(str, Enum):
    """Standard circular resin classifications."""

    PET = "PET"        # Polyethylene Terephthalate
    HDPE = "HDPE"      # High-Density Polyethylene
    PVC = "PVC"        # Polyvinyl Chloride
    LDPE = "LDPE"      # Low-Density Polyethylene
    PP = "PP"          # Polypropylene
    PS = "PS"          # Polystyrene
    MLP = "MLP"        # Multi-Layer Plastic
    OTHER = "OTHER"    # Other / mixed polymers


class Program(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Corporate plastic recovery program specification."""

    __tablename__ = "programs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[str] = mapped_column(
        String(50), nullable=False, default="GLOBAL", index=True
    )
    target_kg: Mapped[float] = mapped_column(Float, nullable=False)
    collected_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    allowed_material_types: Mapped[List[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ProgramStatus] = mapped_column(
        SQLEnum(ProgramStatus, name="program_status_enum", native_enum=False),
        nullable=False,
        default=ProgramStatus.DRAFT,
        index=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        lazy="selectin",
    )
    partners: Mapped[List["ProgramPartner"]] = relationship(
        "ProgramPartner",
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    recoveries: Mapped[List["RecoveryEvent"]] = relationship(
        "RecoveryEvent",
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Program(id={self.id}, name='{self.name}', status='{self.status}')>"


class ProgramPartner(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Assignment of an operational partner organization to a Program."""

    __tablename__ = "program_partners"
    __table_args__ = (
        UniqueConstraint("program_id", "organization_id", name="uq_program_partner"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="COLLECTOR"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # Relationships
    program: Mapped["Program"] = relationship("Program", back_populates="partners", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ProgramPartner(program={self.program_id}, org={self.organization_id}, role='{self.assigned_role}')>"
