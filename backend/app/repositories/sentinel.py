"""PLASTIFY SENTINEL Database Repository."""

from typing import List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evidence import Evidence
from app.models.recovery import RecoveryEvent
from app.models.sentinel import SentinelFlag, SentinelResult
from app.repositories.base import BaseRepository


class SentinelRepository(BaseRepository[SentinelResult]):
    """Data access repository for Sentinel risk assessments and anomaly flags."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SentinelResult, session)

    async def get_by_recovery_id(self, recovery_id: uuid.UUID) -> Optional[SentinelResult]:
        """Fetch Sentinel assessment result by Recovery Event ID with preloaded flags."""
        stmt = (
            select(SentinelResult)
            .where(SentinelResult.recovery_id == recovery_id)
            .options(selectinload(SentinelResult.flags))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_flag(self, flag: SentinelFlag) -> SentinelFlag:
        """Persist a single Sentinel flag."""
        self.session.add(flag)
        await self.session.flush()
        return flag

    async def add_flags(self, flags: List[SentinelFlag]) -> List[SentinelFlag]:
        """Persist multiple Sentinel flags in batch."""
        self.session.add_all(flags)
        await self.session.flush()
        return flags

    async def list_cross_recovery_evidence(
        self, exclude_recovery_id: uuid.UUID, limit: int = 100
    ) -> List[Evidence]:
        """Retrieve recent evidence records from other recovery events for cross-batch matching."""
        stmt = (
            select(Evidence)
            .where(Evidence.recovery_id != exclude_recovery_id)
            .order_by(Evidence.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_collector_history(
        self, collector_id: uuid.UUID, limit: int = 25
    ) -> List[RecoveryEvent]:
        """Retrieve recent recovery history for a specific collector."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.collector_id == collector_id)
            .order_by(RecoveryEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
