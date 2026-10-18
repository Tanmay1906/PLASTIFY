"""PLASTIFY Health and Readiness Service.

Coordinates infrastructure diagnostics for PostgreSQL and Redis.
Decouples health verification logic from route handlers.
"""

import time
from typing import Dict, Tuple

from app.core.config import Settings
from app.core.database import check_db_connection
from app.core.redis import check_redis_connection
from app.schemas.health import (
    ComponentHealth,
    HealthOverviewResponse,
    HealthState,
    LivenessResponse,
    ReadinessResponse,
)
from app.services.base import BaseService

_SERVER_START_TIME = time.time()


class HealthService(BaseService):
    """Service providing liveness, readiness, and comprehensive health status checks."""

    def __init__(
        self,
        settings: Settings,
        db_check=None,
        redis_check=None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self._db_check = db_check or check_db_connection
        self._redis_check = redis_check or check_redis_connection

    def get_liveness(self) -> LivenessResponse:
        """Evaluate process liveness (fast in-memory probe)."""
        return LivenessResponse(status="live")

    async def check_dependencies(self) -> Tuple[HealthState, Dict[str, ComponentHealth]]:
        """Probe PostgreSQL and Redis connections asynchronously."""
        components: Dict[str, ComponentHealth] = {}
        all_healthy = True

        # Check Database
        db_ok, db_lat, db_err = await self._db_check()
        components["postgres"] = ComponentHealth(
            status=HealthState.HEALTHY if db_ok else HealthState.UNHEALTHY,
            latency_ms=db_lat,
            details="Connected to PostgreSQL database cluster" if db_ok else "Database unreachable",
            error=db_err,
        )
        if not db_ok:
            all_healthy = False

        # Check Redis
        redis_ok, redis_lat, redis_err = await self._redis_check()
        components["redis"] = ComponentHealth(
            status=HealthState.HEALTHY if redis_ok else HealthState.UNHEALTHY,
            latency_ms=redis_lat,
            details="Connected to Redis cluster / broker" if redis_ok else "Redis unreachable",
            error=redis_err,
        )
        if not redis_ok:
            all_healthy = False

        overall_state = HealthState.HEALTHY if all_healthy else HealthState.UNHEALTHY
        return overall_state, components

    async def get_readiness(self) -> Tuple[bool, ReadinessResponse]:
        """Perform readiness probe for Kubernetes / container orchestration.

        Returns:
            (is_ready: bool, ReadinessResponse)
        """
        overall_state, components = await self.check_dependencies()
        is_ready = overall_state == HealthState.HEALTHY

        return is_ready, ReadinessResponse(
            status=overall_state,
            components=components,
        )

    async def get_health_overview(self) -> Tuple[bool, HealthOverviewResponse]:
        """Generate comprehensive system health overview."""
        overall_state, components = await self.check_dependencies()
        uptime = round(time.time() - _SERVER_START_TIME, 2)
        is_healthy = overall_state == HealthState.HEALTHY

        return is_healthy, HealthOverviewResponse(
            status=overall_state,
            service=self.settings.PROJECT_NAME,
            version=self.settings.VERSION,
            environment=self.settings.ENVIRONMENT,
            uptime_seconds=uptime,
            components=components,
        )
