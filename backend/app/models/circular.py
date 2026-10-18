"""PLASTIFY Circular Economy Models: Recycling, Upcycling, and Passports.

Entities:
- MaterialBatch: Industrial recycling processing batch converting verified recovered plastic into secondary raw materials.
- MaterialBatchItem: Links verified RecoveryEvents and their allocated input weights to a MaterialBatch.
- MaterialBatchEvidence: Photographic and technical documentation of recycling operations.
- MaterialPassport: Digital product passport for recycled plastic materials.
- UpcyclingBatch: Manufacturing batch converting secondary raw materials into durable circular products.
- UpcyclingAllocation: Allocates recycled material from MaterialBatches to UpcyclingBatches.
- UpcyclingBatchEvidence: Quality and production proof files for upcycled manufacturing.
- Product: Finished circular product registered from an upcycling batch.
- ProductPassport: QR-ready public passport providing full cryptographic provenance from recovery to product.
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
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evidence import Evidence
    from app.models.organization import Organization
    from app.models.recovery import RecoveryEvent
    from app.models.user import User


class MaterialBatchStatus(str, Enum):
    """Lifecycle statuses of an industrial recycling processing batch."""

    CREATED = "CREATED"
    IN_PROCESSING = "IN_PROCESSING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UpcyclingBatchStatus(str, Enum):
    """Lifecycle statuses of an upcycling manufacturing batch."""

    CREATED = "CREATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ------------------------------------------------------------------------------
# 1. Recycling Engine Models
# ------------------------------------------------------------------------------


class MaterialBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Industrial recycling processing batch executing mass balance transformation."""

    __tablename__ = "material_batches"

    batch_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    recycler_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    processor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    material_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    # Mass balance accounting
    input_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    recycled_output_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    residual_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    processing_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status: Mapped[MaterialBatchStatus] = mapped_column(
        SQLEnum(MaterialBatchStatus, name="material_batch_status_enum", native_enum=False),
        nullable=False,
        default=MaterialBatchStatus.CREATED,
        index=True,
    )
    verification_reference: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    recycler_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[recycler_organization_id], lazy="selectin"
    )
    processor: Mapped["User"] = relationship(
        "User", foreign_keys=[processor_id], lazy="selectin"
    )
    items: Mapped[List["MaterialBatchItem"]] = relationship(
        "MaterialBatchItem",
        back_populates="material_batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    evidences: Mapped[List["MaterialBatchEvidence"]] = relationship(
        "MaterialBatchEvidence",
        back_populates="material_batch",
        cascade="all, delete-orphan",
        order_by="MaterialBatchEvidence.created_at.asc()",
        lazy="selectin",
    )
    allocations: Mapped[List["UpcyclingAllocation"]] = relationship(
        "UpcyclingAllocation",
        back_populates="material_batch",
        lazy="selectin",
    )
    passport: Mapped[Optional["MaterialPassport"]] = relationship(
        "MaterialPassport",
        back_populates="material_batch",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def yield_percentage(self) -> float:
        """Percentage yield of recycled output relative to input weight."""
        if self.input_weight_kg <= 0.0:
            return 0.0
        return round((self.recycled_output_kg / self.input_weight_kg) * 100.0, 2)

    @property
    def allocated_upcycling_weight_kg(self) -> float:
        """Total weight in kg drawn by down-stream upcycling batches."""
        return sum(a.allocated_weight_kg for a in self.allocations)

    @property
    def available_for_upcycling_kg(self) -> float:
        """Available unallocated recycled output remaining for upcycling."""
        return max(0.0, round(self.recycled_output_kg - self.allocated_upcycling_weight_kg, 3))

    def __repr__(self) -> str:
        return f"<MaterialBatch(batch_id='{self.batch_id}', status='{self.status}', output={self.recycled_output_kg}kg)>"


class MaterialBatchItem(Base, UUIDPrimaryKeyMixin):
    """Associates verified RecoveryEvents and their specific drawn weights to a MaterialBatch."""

    __tablename__ = "material_batch_items"
    __table_args__ = (
        UniqueConstraint("material_batch_id", "recovery_event_id", name="uq_batch_recovery"),
    )

    material_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recovery_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    allocated_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    material_batch: Mapped["MaterialBatch"] = relationship(
        "MaterialBatch", back_populates="items"
    )
    recovery: Mapped["RecoveryEvent"] = relationship(
        "RecoveryEvent", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<MaterialBatchItem(batch_id={self.material_batch_id}, recovery_id={self.recovery_event_id}, weight={self.allocated_weight_kg}kg)>"


class MaterialBatchEvidence(Base, UUIDPrimaryKeyMixin):
    """Processing and weight evidence associated with a recycling batch."""

    __tablename__ = "material_batch_evidences"

    material_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_batches.id", ondelete="CASCADE"),
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
        String(50), nullable=False, default="PROCESSING_PROOF", index=True
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
    material_batch: Mapped["MaterialBatch"] = relationship(
        "MaterialBatch", back_populates="evidences"
    )
    uploader: Mapped["User"] = relationship("User", lazy="selectin")
    evidence: Mapped[Optional["Evidence"]] = relationship("Evidence", lazy="selectin")

    def __repr__(self) -> str:
        return f"<MaterialBatchEvidence(id={self.id}, type='{self.evidence_type}')>"


class MaterialPassport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Digital Material Passport providing provenance and mass balance credentials."""

    __tablename__ = "material_passports"

    passport_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    material_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_batches.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    qr_code_identifier: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    issuer_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    material_batch: Mapped["MaterialBatch"] = relationship(
        "MaterialBatch", back_populates="passport", lazy="selectin"
    )
    issuer_organization: Mapped["Organization"] = relationship(
        "Organization", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<MaterialPassport(code='{self.passport_code}', batch_id={self.material_batch_id})>"


# ------------------------------------------------------------------------------
# 2. Upcycling Engine Models
# ------------------------------------------------------------------------------


class UpcyclingBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Manufacturing batch converting secondary plastic flakes/pellets into circular products."""

    __tablename__ = "upcycling_batches"

    batch_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    upcycler_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    total_input_material_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quantity_produced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False, default="UNITS")

    # Quality Verification
    quality_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    quality_rating: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    quality_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_verified_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quality_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[UpcyclingBatchStatus] = mapped_column(
        SQLEnum(UpcyclingBatchStatus, name="upcycling_batch_status_enum", native_enum=False),
        nullable=False,
        default=UpcyclingBatchStatus.CREATED,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    upcycler_organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[upcycler_organization_id], lazy="selectin"
    )
    creator: Mapped["User"] = relationship(
        "User", foreign_keys=[creator_id], lazy="selectin"
    )
    quality_verifier: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[quality_verified_by_id], lazy="selectin"
    )
    allocations: Mapped[List["UpcyclingAllocation"]] = relationship(
        "UpcyclingAllocation",
        back_populates="upcycling_batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    products: Mapped[List["Product"]] = relationship(
        "Product",
        back_populates="upcycling_batch",
        lazy="selectin",
    )
    evidences: Mapped[List["UpcyclingBatchEvidence"]] = relationship(
        "UpcyclingBatchEvidence",
        back_populates="upcycling_batch",
        cascade="all, delete-orphan",
        order_by="UpcyclingBatchEvidence.created_at.asc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<UpcyclingBatch(batch_id='{self.batch_id}', status='{self.status}', qty={self.quantity_produced})>"


class UpcyclingAllocation(Base, UUIDPrimaryKeyMixin):
    """Allocates a discrete quantity of recycled output from a MaterialBatch to an UpcyclingBatch."""

    __tablename__ = "upcycling_allocations"
    __table_args__ = (
        UniqueConstraint("upcycling_batch_id", "material_batch_id", name="uq_upcycling_allocation"),
    )

    upcycling_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upcycling_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    allocated_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    upcycling_batch: Mapped["UpcyclingBatch"] = relationship(
        "UpcyclingBatch", back_populates="allocations"
    )
    material_batch: Mapped["MaterialBatch"] = relationship(
        "MaterialBatch", back_populates="allocations", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<UpcyclingAllocation(upcycling_id={self.upcycling_batch_id}, material_id={self.material_batch_id}, weight={self.allocated_weight_kg}kg)>"


class UpcyclingBatchEvidence(Base, UUIDPrimaryKeyMixin):
    """Technical, QA, and manufacturing evidence for upcycling batches."""

    __tablename__ = "upcycling_batch_evidences"

    upcycling_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upcycling_batches.id", ondelete="CASCADE"),
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
        String(50), nullable=False, default="PRODUCTION_PROOF", index=True
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
    upcycling_batch: Mapped["UpcyclingBatch"] = relationship(
        "UpcyclingBatch", back_populates="evidences"
    )
    uploader: Mapped["User"] = relationship("User", lazy="selectin")
    evidence: Mapped[Optional["Evidence"]] = relationship("Evidence", lazy="selectin")

    def __repr__(self) -> str:
        return f"<UpcyclingBatchEvidence(id={self.id}, type='{self.evidence_type}')>"


# ------------------------------------------------------------------------------
# 3. Product and Product Passport Models
# ------------------------------------------------------------------------------


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Finished consumer or commercial product manufactured from upcycled plastic."""

    __tablename__ = "products"

    product_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    upcycling_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upcycling_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    weight_per_unit_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recycled_content_percentage: Mapped[float] = mapped_column(
        Float, nullable=False, default=100.0
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    upcycling_batch: Mapped["UpcyclingBatch"] = relationship(
        "UpcyclingBatch", back_populates="products", lazy="selectin"
    )
    passports: Mapped[List["ProductPassport"]] = relationship(
        "ProductPassport",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Product(code='{self.product_code}', name='{self.name}', type='{self.product_type}')>"


class ProductPassport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """QR-ready Digital Product Passport connecting product to origin recoveries."""

    __tablename__ = "product_passports"

    passport_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upcycling_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upcycling_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    qr_code_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    public_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="passports", lazy="selectin")
    upcycling_batch: Mapped["UpcyclingBatch"] = relationship("UpcyclingBatch", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ProductPassport(passport_id='{self.passport_id}', product_id={self.product_id})>"
