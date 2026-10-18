"""PLASTIFY Evidence Metadata Repository.

Encapsulates database access for digital evidence metadata.
All binary files reside in S3/MinIO; only cryptographic metadata is stored in PostgreSQL.
"""

from typing import List, Optional
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evidence import Evidence
from app.repositories.base import BaseRepository


class EvidenceRepository(BaseRepository[Evidence]):
    """Repository managing digital proof and evidence metadata records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Evidence, session)

    async def get_with_relations(self, evidence_id: uuid.UUID) -> Optional[Evidence]:
        """Fetch evidence record with uploader and recovery event eagerly loaded."""
        stmt = (
            select(Evidence)
            .where(Evidence.id == evidence_id)
            .options(
                selectinload(Evidence.uploader),
                selectinload(Evidence.recovery),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_recovery(
        self, recovery_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> List[Evidence]:
        """List all evidence attached to a specific recovery event ordered chronologically."""
        stmt = (
            select(Evidence)
            .where(Evidence.recovery_id == recovery_id)
            .order_by(Evidence.created_at.asc())
            .offset(skip)
            .limit(limit)
            .options(selectinload(Evidence.uploader))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_recovery(self, recovery_id: uuid.UUID) -> int:
        """Count total evidence files attached to a recovery event."""
        stmt = (
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.recovery_id == recovery_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
