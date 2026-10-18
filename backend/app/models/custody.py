"""PLASTIFY Chain-of-Custody Immutable Event Models.

Records the full, auditable physical lifecycle transitions of recovered plastic materials
from collection through processing and circular transformation.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid
from sqlalchemy import (
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class CustodyState(str, Enum):
    """Immutable sequential chain-of-custody milestones."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PICKUP_ASSIGNED = "PICKUP_ASSIGNED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"


class ChainOfCustodyEvent(Base, UUIDPrimaryKeyMixin):
    """Immutable audit trail record for each chain-of-custody state transition."""

    __tablename__ = "chain_of_custody_events"

    # Human-readable or composite resource identifier (e.g., 'POP-DEL-2026-000184')
    resource: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="RECOVERY_EVENT", index=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    previous_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_state: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    event_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    actor: Mapped["User"] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ChainOfCustodyEvent(resource='{self.resource}', {self.previous_state} -> {self.new_state})>"
