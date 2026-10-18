"""PLASTIFY System Audit Repository."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SystemAuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[SystemAuditLog]):
    """Repository handling persistence and querying of system audit records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SystemAuditLog, session)

    async def create_log(
        self,
        event_type: str,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> SystemAuditLog:
        """Create and persist an audit log entry."""
        log = SystemAuditLog(
            event_type=event_type,
            component=component,
            message=message,
            request_id=request_id,
            details=details,
        )
        return await self.create(log)

    async def record(
        self,
        action: str,
        resource: str,
        actor_id: Optional[Any] = None,
        actor_email: Optional[str] = None,
        actor_role: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> SystemAuditLog:
        """Convenience method to record an audit event for resources and actors."""
        details: Dict[str, Any] = dict(metadata or {})
        if actor_id is not None:
            details["actor_id"] = str(actor_id)
        if actor_email:
            details["actor_email"] = actor_email
        if actor_role:
            details["actor_role"] = actor_role
        details["resource"] = resource

        component = resource.split(":")[0] if ":" in resource else resource
        actor_desc = actor_email or (str(actor_id) if actor_id else "system")
        message = f"{action} on {resource} by {actor_desc}"

        return await self.create_log(
            event_type=action,
            component=component,
            message=message,
            request_id=request_id,
            details=details,
        )

    async def get_by_event_type(self, event_type: str, limit: int = 50) -> List[SystemAuditLog]:
        """Fetch audit logs filtered by event_type."""
        query = (
            select(SystemAuditLog)
            .where(SystemAuditLog.event_type == event_type)
            .order_by(SystemAuditLog.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
