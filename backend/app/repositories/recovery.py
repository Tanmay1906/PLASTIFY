"""PLASTIFY Recovery Event and Audit History Repositories."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.recovery import (
    RecoveryEvent,
    RecoveryEventHistory,
    RecoverySequence,
)
from app.repositories.base import BaseRepository


class RecoveryRepository(BaseRepository[RecoveryEvent]):
    """Data access repository for plastic collection and recovery events."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RecoveryEvent, session)

    async def get_by_recovery_id(self, recovery_id: str) -> Optional[RecoveryEvent]:
        """Fetch recovery event by human-readable immutable recovery ID."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.recovery_id == recovery_id.strip())
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
                selectinload(RecoveryEvent.history),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_with_details(self, event_id: uuid.UUID) -> Optional[RecoveryEvent]:
        """Fetch recovery event by primary key with all associations eager-loaded."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.id == event_id)
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
                selectinload(RecoveryEvent.history),
                selectinload(RecoveryEvent.sentinel_result),
                selectinload(RecoveryEvent.evidence),
                selectinload(RecoveryEvent.verification_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_collector(
        self, collector_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[RecoveryEvent]:
        """Fetch recovery events created by a specific collector user."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.collector_id == collector_id)
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
            )
            .order_by(RecoveryEvent.collected_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_collector_organization(
        self, org_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[RecoveryEvent]:
        """Fetch all recovery events submitted under a collector organization."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.collector_organization_id == org_id)
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
            )
            .order_by(RecoveryEvent.collected_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_program(
        self, program_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[RecoveryEvent]:
        """Fetch all recovery events for a specific recovery program."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.program_id == program_id)
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
            )
            .order_by(RecoveryEvent.collected_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_next_recovery_id(self, region: str, year: int) -> str:
        """Atomically generate official human-readable Recovery ID (e.g. POP-DEL-2026-000184).

        Guarantees monotonicity, collision-freedom, and immutability.
        """
        clean_region = region.strip().upper()[:10]
        prefix = f"POP-{clean_region}-{year}"

        # Fetch with row lock (or fallback in SQLite test env)
        stmt = (
            select(RecoverySequence)
            .where(RecoverySequence.prefix == prefix)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        seq_record = result.scalars().first()

        if not seq_record:
            seq_record = RecoverySequence(prefix=prefix, last_sequence=1)
            self.session.add(seq_record)
        else:
            seq_record.last_sequence += 1

        await self.session.flush()
        return f"{prefix}-{seq_record.last_sequence:06d}"


class RecoveryHistoryRepository(BaseRepository[RecoveryEventHistory]):
    """Data access repository for immutable state transition history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RecoveryEventHistory, session)

    async def record_transition(
        self,
        recovery_event_id: uuid.UUID,
        from_status: Optional[str],
        to_status: str,
        actor_id: uuid.UUID,
        actor_role: str,
        notes: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
    ) -> RecoveryEventHistory:
        """Persist an immutable audit record of a state transition."""
        history = RecoveryEventHistory(
            recovery_event_id=recovery_event_id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            actor_role=actor_role,
            notes=notes,
            event_metadata=event_metadata,
            created_at=datetime.now(timezone.utc),
        )
        return await self.create(history)

    async def list_for_event(
        self, recovery_event_id: uuid.UUID
    ) -> List[RecoveryEventHistory]:
        """Fetch all state transition records for a recovery event ordered chronologically."""
        stmt = (
            select(RecoveryEventHistory)
            .where(RecoveryEventHistory.recovery_event_id == recovery_event_id)
            .order_by(RecoveryEventHistory.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
