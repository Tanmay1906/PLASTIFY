"""PLASTIFY SENTINEL Risk and Anomaly Detection Models."""

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
    from app.models.recovery import RecoveryEvent


class RiskLevel(str, Enum):
    """Categorical risk severity assigned by Sentinel detectors."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SentinelStatus(str, Enum):
    """Lifecycle status of a Sentinel analysis evaluation."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SentinelResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Summary of automated risk and anomaly detection for a Recovery Event."""

    __tablename__ = "sentinel_results"

    recovery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recovery_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[RiskLevel] = mapped_column(
        SQLEnum(RiskLevel, name="risk_level_enum", native_enum=False),
        nullable=False,
        default=RiskLevel.LOW,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    flags_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[SentinelStatus] = mapped_column(
        SQLEnum(SentinelStatus, name="sentinel_status_enum", native_enum=False),
        nullable=False,
        default=SentinelStatus.COMPLETED,
        index=True,
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    recovery: Mapped["RecoveryEvent"] = relationship(
        "RecoveryEvent", back_populates="sentinel_result", lazy="selectin"
    )
    flags: Mapped[List["SentinelFlag"]] = relationship(
        "SentinelFlag",
        back_populates="result",
        cascade="all, delete-orphan",
        order_by="SentinelFlag.created_at.asc()",
        lazy="selectin",
    )


class SentinelFlag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Individual anomaly or risk finding flagged by a Sentinel detector."""

    __tablename__ = "sentinel_flags"

    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sentinel_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    detector: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[RiskLevel] = mapped_column(
        SQLEnum(RiskLevel, name="sentinel_flag_severity_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    evidence_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    result: Mapped["SentinelResult"] = relationship(
        "SentinelResult", back_populates="flags", lazy="selectin"
    )
