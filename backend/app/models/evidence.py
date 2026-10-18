"""PLASTIFY Evidence Management ORM Models.

Stores cryptographic and object storage metadata for digital proof files
(photos, scale receipts, delivery bills of lading, processing logs).
Binary files are strictly stored in S3/MinIO and NEVER in PostgreSQL.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
import uuid
from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.recovery import RecoveryEvent
    from app.models.user import User


class EvidenceType(str, Enum):
    """Categorization of recovery verification evidence."""

    COLLECTION_PHOTO = "COLLECTION_PHOTO"
    WEIGHT_PHOTO = "WEIGHT_PHOTO"
    RECEIPT = "RECEIPT"
    DELIVERY_PROOF = "DELIVERY_PROOF"
    PROCESSING_PROOF = "PROCESSING_PROOF"
    OTHER = "OTHER"


class Evidence(Base, UUIDPrimaryKeyMixin):
    """Metadata record for an uploaded evidence file stored in S3/MinIO."""

    __tablename__ = "evidence"

    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    type: Mapped[EvidenceType] = mapped_column(
        SQLEnum(EvidenceType, name="evidence_type_enum", native_enum=False),
        nullable=False,
        default=EvidenceType.OTHER,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)  # in bytes
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scan_status: Mapped[str] = mapped_column(String(50), nullable=False, default="CLEAN")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship(
        "RecoveryEvent", back_populates="evidence", lazy="selectin"
    )
    uploader: Mapped["User"] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Evidence(id={self.id}, type='{self.type}', hash='{self.sha256_hash[:8]}...')>"
