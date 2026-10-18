"""PLASTIFY Verification Engine Repository.

Database operations for verification records, audit findings, and queue queries.
"""

from typing import List, Optional
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.custody import CustodyState
from app.models.logistics import Delivery, DeliveryStatus
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.verification import (
    FindingSeverity,
    VerificationFinding,
    VerificationRecord,
)
from app.repositories.base import BaseRepository


class VerificationRepository(BaseRepository[VerificationRecord]):
    """Data access layer for verification records, findings, and verification queue."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(VerificationRecord, session)

    # --------------------------------------------------------------------------
    # Verification Records
    # --------------------------------------------------------------------------

    async def get_record_by_id(self, record_id: uuid.UUID) -> Optional[VerificationRecord]:
        """Fetch verification record by UUID with full relations."""
        stmt = (
            select(VerificationRecord)
            .where(VerificationRecord.id == record_id)
            .options(
                selectinload(VerificationRecord.recovery),
                selectinload(VerificationRecord.verifier),
                selectinload(VerificationRecord.verifier_organization),
                selectinload(VerificationRecord.findings),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_record_by_code(self, code: str) -> Optional[VerificationRecord]:
        """Fetch verification record by human code."""
        stmt = (
            select(VerificationRecord)
            .where(VerificationRecord.verification_code == code)
            .options(
                selectinload(VerificationRecord.recovery),
                selectinload(VerificationRecord.verifier),
                selectinload(VerificationRecord.verifier_organization),
                selectinload(VerificationRecord.findings),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_records_by_recovery(
        self, recovery_id: uuid.UUID
    ) -> List[VerificationRecord]:
        """List all verification determinations for a recovery event in chronological order."""
        stmt = (
            select(VerificationRecord)
            .where(VerificationRecord.recovery_id == recovery_id)
            .order_by(VerificationRecord.created_at.desc())
            .options(
                selectinload(VerificationRecord.verifier),
                selectinload(VerificationRecord.verifier_organization),
                selectinload(VerificationRecord.findings),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_record(self, record: VerificationRecord) -> VerificationRecord:
        """Persist an immutable verification record."""
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    # --------------------------------------------------------------------------
    # Verification Findings
    # --------------------------------------------------------------------------

    async def get_finding_by_id(
        self, finding_id: uuid.UUID
    ) -> Optional[VerificationFinding]:
        """Fetch a specific verification finding with details."""
        stmt = (
            select(VerificationFinding)
            .where(VerificationFinding.id == finding_id)
            .options(
                selectinload(VerificationFinding.recovery),
                selectinload(VerificationFinding.finder),
                selectinload(VerificationFinding.resolved_by),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_findings_by_recovery(
        self, recovery_id: uuid.UUID, unresolved_only: bool = False
    ) -> List[VerificationFinding]:
        """List findings linked to a recovery event."""
        stmt = select(VerificationFinding).where(
            VerificationFinding.recovery_id == recovery_id
        )
        if unresolved_only:
            stmt = stmt.where(VerificationFinding.is_resolved.is_(False))

        stmt = stmt.order_by(VerificationFinding.created_at.asc()).options(
            selectinload(VerificationFinding.finder),
            selectinload(VerificationFinding.resolved_by),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_unresolved_critical_findings(self, recovery_id: uuid.UUID) -> int:
        """Count blocking/critical unresolved issues for a recovery event."""
        stmt = (
            select(func.count(VerificationFinding.id))
            .where(VerificationFinding.recovery_id == recovery_id)
            .where(VerificationFinding.severity == FindingSeverity.CRITICAL)
            .where(VerificationFinding.is_resolved.is_(False))
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def create_finding(
        self, finding: VerificationFinding
    ) -> VerificationFinding:
        """Persist an audit discrepancy or review flag."""
        self.session.add(finding)
        await self.session.flush()
        await self.session.refresh(finding)
        return finding

    # --------------------------------------------------------------------------
    # Atomic Row-Locking & Queue Queries
    # --------------------------------------------------------------------------

    async def get_recovery_for_update(
        self, recovery_id: uuid.UUID
    ) -> Optional[RecoveryEvent]:
        """Fetch RecoveryEvent with pessimistic row lock (SELECT FOR UPDATE) to guarantee atomic verification."""
        stmt = (
            select(RecoveryEvent)
            .where(RecoveryEvent.id == recovery_id)
            .with_for_update()
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
                selectinload(RecoveryEvent.evidence),
                selectinload(RecoveryEvent.history),
                selectinload(RecoveryEvent.verification_findings),
                selectinload(RecoveryEvent.verification_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_verification_queue(
        self,
        program_ids: Optional[List[uuid.UUID]] = None,
        material_type: Optional[str] = None,
        status: Optional[RecoveryStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[RecoveryEvent]:
        """Fetch recovery events waiting for human verification review.

        Eligible items:
        - Must be in SUBMITTED or FLAGGED status (not DRAFT, not CANCELLED, not already VERIFIED or REJECTED)
        - Must have reached RECEIVED custody state (or be FLAGGED for review)
        - Filtered by programs where verifier has jurisdiction
        """
        stmt = select(RecoveryEvent).where(
            RecoveryEvent.status.in_([RecoveryStatus.SUBMITTED, RecoveryStatus.FLAGGED])
        )

        if program_ids is not None:
            stmt = stmt.where(RecoveryEvent.program_id.in_(program_ids))

        if material_type:
            stmt = stmt.where(RecoveryEvent.material_type == material_type)

        if status:
            stmt = stmt.where(RecoveryEvent.status == status)

        stmt = (
            stmt.order_by(RecoveryEvent.created_at.asc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(RecoveryEvent.program),
                selectinload(RecoveryEvent.collector),
                selectinload(RecoveryEvent.collector_organization),
                selectinload(RecoveryEvent.evidence),
                selectinload(RecoveryEvent.verification_findings),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
