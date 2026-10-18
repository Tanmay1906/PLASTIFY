"""PLASTIFY Chain-of-Custody Repository.

Append-only repository managing immutable chain-of-custody milestones.
Strictly does NOT expose update or delete methods to preserve audit integrity.
"""

from typing import List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.custody import ChainOfCustodyEvent
from app.repositories.base import BaseRepository


class ChainOfCustodyRepository(BaseRepository[ChainOfCustodyEvent]):
    """Append-only repository for immutable chain-of-custody transition logs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ChainOfCustodyEvent, session)

    async def record_event(
        self, event: ChainOfCustodyEvent
    ) -> ChainOfCustodyEvent:
        """Persist a new immutable chain-of-custody event."""
        return await self.create(event)

    async def list_for_resource(
        self, resource_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[ChainOfCustodyEvent]:
        """Retrieve chronological history of custody events for a resource."""
        stmt = (
            select(ChainOfCustodyEvent)
            .where(ChainOfCustodyEvent.resource_id == resource_id)
            .order_by(ChainOfCustodyEvent.timestamp.asc())
            .offset(skip)
            .limit(limit)
            .options(selectinload(ChainOfCustodyEvent.actor))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_resource(
        self, resource_id: uuid.UUID
    ) -> Optional[ChainOfCustodyEvent]:
        """Fetch the most recent chain-of-custody transition for a resource."""
        stmt = (
            select(ChainOfCustodyEvent)
            .where(ChainOfCustodyEvent.resource_id == resource_id)
            .order_by(ChainOfCustodyEvent.timestamp.desc())
            .limit(1)
            .options(selectinload(ChainOfCustodyEvent.actor))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
