"""PLASTIFY Foundation Audit Log Model.

Captures system events, correlation IDs, and actor records for compliance
and traceability throughout the plastic recovery lifecycle.
"""

from typing import Any, Dict, Optional
from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SystemAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """System-level audit log entry."""

    __tablename__ = "system_audit_logs"

    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<SystemAuditLog(id={self.id}, event_type='{self.event_type}', component='{self.component}')>"
