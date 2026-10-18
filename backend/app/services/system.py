"""PLASTIFY System Diagnostic Service."""

import sys
from typing import Any, Dict, Optional

from app.core.config import Settings
from app.models.audit import SystemAuditLog
from app.repositories.audit import AuditRepository
from app.schemas.system import PingResponse, SystemInfoResponse
from app.services.base import BaseService


class SystemService(BaseService):
    """Encapsulates system-level diagnostic operations."""

    def __init__(self, settings: Settings, audit_repo: Optional[AuditRepository] = None) -> None:
        super().__init__()
        self.settings = settings
        self.audit_repo = audit_repo

    def get_system_info(self) -> SystemInfoResponse:
        """Collect high-level runtime metadata."""
        return SystemInfoResponse(
            app_name=self.settings.PROJECT_NAME,
            version=self.settings.VERSION,
            environment=self.settings.ENVIRONMENT,
            api_prefix=self.settings.API_V1_STR,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            debug_mode=self.settings.DEBUG,
        )

    def ping(self, request_id: Optional[str] = None) -> PingResponse:
        """Respond to ping requests."""
        return PingResponse(
            message="pong",
            request_id=request_id,
        )

    async def log_system_event(
        self,
        event_type: str,
        component: str,
        message: str,
        request_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[SystemAuditLog]:
        """Record a system audit entry if repository is available."""
        if self.audit_repo:
            return await self.audit_repo.create_log(
                event_type=event_type,
                component=component,
                message=message,
                request_id=request_id,
                details=details,
            )
        return None
