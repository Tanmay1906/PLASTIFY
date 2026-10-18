"""PLASTIFY Plastic Credit, Issuance, Transaction, and Retirement Models.

Entities:
- CreditBatchStatus: Lifecycle states of a plastic credit issuance batch
- CreditBatch: Formal issuance container grouping verified eligible impact allocations
- CreditStatus: Status of serialized credit tranches (ACTIVE, RETIRED, REVOKED)
- PlasticCredit: Serialized credit unit representation
- TransactionType: Auditable credit movement classification (ISSUANCE, TRANSFER, RETIREMENT, REVOCATION)
- CreditTransaction: Cryptographically-hashed ownership and transfer ledger
- CreditRetirement: Terminal, non-reusable environmental retirement certificate
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
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.impact import ImpactAllocation, MethodologyVersion
    from app.models.organization import Organization
    from app.models.user import User


class CreditBatchStatus(str, Enum):
    """Lifecycle statuses of a credit issuance batch."""

    DRAFT = "DRAFT"                               # Formed from assessed impacts, awaiting independent approval
    APPROVED = "APPROVED"                         # Approved by authorized verifier / credit authority
    ISSUED = "ISSUED"                             # Minted and released into active circulation
    RETIRED = "RETIRED"                           # 100% of credits in batch have been retired
    REVOKED = "REVOKED"                           # Revoked by audit or compliance determination


class CreditStatus(str, Enum):
    """Circulation status of a serialized plastic credit block."""

    ACTIVE = "ACTIVE"                             # Freely tradeable / transferable / eligible for retirement
    ALLOCATED = "ALLOCATED"                       # Held in escrow for contract or transfer
    RETIRED = "RETIRED"                           # Terminally consumed / retired (never reusable or transferable)
    REVOKED = "REVOKED"                           # Cancelled


class TransactionType(str, Enum):
    """Action categories for immutable credit ledger transactions."""

    ISSUANCE = "ISSUANCE"                         # Initial minting
    TRANSFER = "TRANSFER"                         # Ownership change between organizations
    RETIREMENT = "RETIREMENT"                     # Terminal consumption on behalf of a beneficiary
    REVOCATION = "REVOCATION"                     # Audit-mandated cancellation


# ------------------------------------------------------------------------------
# 1. Credit Batch
# ------------------------------------------------------------------------------

class CreditBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Auditable issuance container for plastic credits backed by verified impact."""

    __tablename__ = "credit_batches"
    __table_args__ = (
        CheckConstraint("total_credits > 0", name="chk_credit_batch_total_positive"),
        CheckConstraint("available_credits >= 0", name="chk_credit_batch_avail_non_neg"),
        CheckConstraint("retired_credits >= 0", name="chk_credit_batch_retired_non_neg"),
        CheckConstraint("available_credits + retired_credits <= total_credits", name="chk_credit_batch_sum_lte_total"),
    )

    # Unique batch code: e.g. CRB-2026-MUM-PET-0001
    batch_number: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    methodology_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("methodology_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    issuer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Exact decimal amounts
    total_credits: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    available_credits: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    retired_credits: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False, default=Decimal("0.0000")
    )
    credit_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PLASTIC_RECOVERY_CREDIT"
    )
    vintage_year: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[CreditBatchStatus] = mapped_column(
        SQLEnum(CreditBatchStatus, name="credit_batch_status_enum", native_enum=False),
        nullable=False,
        default=CreditBatchStatus.DRAFT,
        index=True,
    )

    # External Registry Integration
    registry_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="PLASTIFY_INTERNAL_REGISTRY"
    )
    registry_batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    registry_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="LOCAL_ONLY"
    )  # LOCAL_ONLY, SYNCED, PENDING_RECONCILIATION, FAILED
    is_mock_issuance: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Idempotency and anti-replay
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    issuance_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[organization_id], lazy="selectin"
    )
    methodology_version: Mapped["MethodologyVersion"] = relationship(
        "MethodologyVersion", foreign_keys=[methodology_version_id], lazy="selectin"
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[creator_id], lazy="selectin")
    approver: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approver_id], lazy="selectin")
    issuer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[issuer_id], lazy="selectin")

    impact_allocations: Mapped[List["ImpactAllocation"]] = relationship(
        "ImpactAllocation", back_populates="credit_batch", lazy="selectin"
    )
    credits: Mapped[List["PlasticCredit"]] = relationship(
        "PlasticCredit", back_populates="credit_batch", cascade="all, delete-orphan", lazy="selectin"
    )
    retirements: Mapped[List["CreditRetirement"]] = relationship(
        "CreditRetirement", back_populates="credit_batch", cascade="all, delete-orphan", lazy="selectin"
    )
    transactions: Mapped[List["CreditTransaction"]] = relationship(
        "CreditTransaction", back_populates="credit_batch", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<CreditBatch(batch='{self.batch_number}', status='{self.status}', credits={self.total_credits})>"


# ------------------------------------------------------------------------------
# 2. Serialized Plastic Credit
# ------------------------------------------------------------------------------

class PlasticCredit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Serialized auditable plastic credit tranche."""

    __tablename__ = "plastic_credits"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_credit_quantity_positive"),
        CheckConstraint("serial_start <= serial_end", name="chk_credit_serial_range"),
    )

    credit_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    serial_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    serial_start: Mapped[int] = mapped_column(Integer, nullable=False)
    serial_end: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    owner_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[CreditStatus] = mapped_column(
        SQLEnum(CreditStatus, name="credit_status_enum", native_enum=False),
        nullable=False,
        default=CreditStatus.ACTIVE,
        index=True,
    )
    vintage_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    credit_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relationships
    credit_batch: Mapped["CreditBatch"] = relationship("CreditBatch", back_populates="credits", lazy="selectin")
    owner_organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")

    def __repr__(self) -> str:
        return f"<PlasticCredit(sn='{self.serial_number}', qty={self.quantity}, status='{self.status}')>"


# ------------------------------------------------------------------------------
# 3. Credit Transaction (Ownership Ledger)
# ------------------------------------------------------------------------------

class CreditTransaction(Base, UUIDPrimaryKeyMixin):
    """Immutable audit trail of credit issuance, transfer, retirement, or revocation."""

    __tablename__ = "credit_transactions"

    transaction_id: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, index=True
    )
    credit_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("plastic_credits.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    tx_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, name="transaction_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    from_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    to_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    audit_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    credit_batch: Mapped["CreditBatch"] = relationship("CreditBatch", back_populates="transactions", lazy="selectin")
    from_organization: Mapped[Optional["Organization"]] = relationship("Organization", foreign_keys=[from_organization_id], lazy="selectin")
    to_organization: Mapped[Optional["Organization"]] = relationship("Organization", foreign_keys=[to_organization_id], lazy="selectin")
    actor: Mapped["User"] = relationship("User", foreign_keys=[actor_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<CreditTransaction(id='{self.transaction_id}', type='{self.tx_type}', qty={self.quantity})>"


# ------------------------------------------------------------------------------
# 4. Credit Retirement
# ------------------------------------------------------------------------------

class CreditRetirement(Base, UUIDPrimaryKeyMixin):
    """Terminal, permanent retirement certificate record."""

    __tablename__ = "credit_retirements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_retirement_quantity_positive"),
    )

    retirement_id: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, index=True
    )
    credit_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("plastic_credits.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    retiring_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4, asdecimal=True), nullable=False
    )
    beneficiary_name: Mapped[str] = mapped_column(String(255), nullable=False)
    retirement_reason: Mapped[str] = mapped_column(Text, nullable=False)
    certificate_id: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    certificate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )

    retired_at: Mapped[datetime] = mapped_column(
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
    credit_batch: Mapped["CreditBatch"] = relationship("CreditBatch", back_populates="retirements", lazy="selectin")
    retiring_organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    actor: Mapped["User"] = relationship("User", foreign_keys=[actor_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<CreditRetirement(cert='{self.certificate_id}', qty={self.quantity}, beneficiary='{self.beneficiary_name}')>"
