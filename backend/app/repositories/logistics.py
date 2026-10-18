"""PLASTIFY Logistics and Delivery Repository.

Handles persistence, querying, and relationship loading for:
- LogisticsAssignment
- Delivery
- DeliveryEvidence
"""

from typing import List, Optional
import uuid
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.logistics import (
    AssignmentStatus,
    Delivery,
    DeliveryEvidence,
    DeliveryStatus,
    LogisticsAssignment,
)
from app.repositories.base import BaseRepository


class LogisticsRepository(BaseRepository[LogisticsAssignment]):
    """Repository managing logistics transport assignments and delivery operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(LogisticsAssignment, session)

    # --------------------------------------------------------------------------
    # Assignment Queries
    # --------------------------------------------------------------------------

    async def create_assignment(
        self, assignment: LogisticsAssignment
    ) -> LogisticsAssignment:
        """Persist a new logistics assignment."""
        return await self.create(assignment)

    async def get_assignment_by_id(
        self, assignment_id: uuid.UUID
    ) -> Optional[LogisticsAssignment]:
        """Fetch assignment with eagerly loaded relationships."""
        stmt = (
            select(LogisticsAssignment)
            .where(LogisticsAssignment.id == assignment_id)
            .options(
                selectinload(LogisticsAssignment.recovery),
                selectinload(LogisticsAssignment.program),
                selectinload(LogisticsAssignment.logistics_organization),
                selectinload(LogisticsAssignment.destination_organization),
                selectinload(LogisticsAssignment.assigned_by),
                selectinload(LogisticsAssignment.assigned_to_driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.logistics_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.recycler_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.receiver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_assignment_by_recovery_id(
        self, recovery_id: uuid.UUID
    ) -> Optional[LogisticsAssignment]:
        """Fetch active assignment linked to a recovery event."""
        stmt = (
            select(LogisticsAssignment)
            .where(LogisticsAssignment.recovery_id == recovery_id)
            .order_by(LogisticsAssignment.created_at.desc())
            .options(
                selectinload(LogisticsAssignment.recovery),
                selectinload(LogisticsAssignment.program),
                selectinload(LogisticsAssignment.logistics_organization),
                selectinload(LogisticsAssignment.destination_organization),
                selectinload(LogisticsAssignment.assigned_by),
                selectinload(LogisticsAssignment.assigned_to_driver),
                selectinload(LogisticsAssignment.delivery),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_assignments(
        self,
        logistics_org_id: Optional[uuid.UUID] = None,
        status: Optional[AssignmentStatus] = None,
        program_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[LogisticsAssignment]:
        """List assignments filtered by logistics org, status, and program."""
        stmt = select(LogisticsAssignment)

        if logistics_org_id:
            stmt = stmt.where(LogisticsAssignment.logistics_organization_id == logistics_org_id)
        if status:
            stmt = stmt.where(LogisticsAssignment.status == status)
        if program_id:
            stmt = stmt.where(LogisticsAssignment.program_id == program_id)

        stmt = (
            stmt.order_by(LogisticsAssignment.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(LogisticsAssignment.recovery),
                selectinload(LogisticsAssignment.program),
                selectinload(LogisticsAssignment.logistics_organization),
                selectinload(LogisticsAssignment.destination_organization),
                selectinload(LogisticsAssignment.assigned_by),
                selectinload(LogisticsAssignment.assigned_to_driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.logistics_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.recycler_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.receiver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_available_assignments(
        self,
        logistics_org_id: Optional[uuid.UUID] = None,
        program_ids: Optional[List[uuid.UUID]] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[LogisticsAssignment]:
        """List assignments available for pickup (in ASSIGNED status)."""
        stmt = select(LogisticsAssignment).where(
            LogisticsAssignment.status == AssignmentStatus.ASSIGNED
        )

        if logistics_org_id and program_ids:
            stmt = stmt.where(
                or_(
                    LogisticsAssignment.logistics_organization_id == logistics_org_id,
                    LogisticsAssignment.program_id.in_(program_ids),
                )
            )
        elif logistics_org_id:
            stmt = stmt.where(LogisticsAssignment.logistics_organization_id == logistics_org_id)
        elif program_ids:
            stmt = stmt.where(LogisticsAssignment.program_id.in_(program_ids))

        stmt = (
            stmt.order_by(LogisticsAssignment.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(LogisticsAssignment.recovery),
                selectinload(LogisticsAssignment.program),
                selectinload(LogisticsAssignment.logistics_organization),
                selectinload(LogisticsAssignment.destination_organization),
                selectinload(LogisticsAssignment.assigned_by),
                selectinload(LogisticsAssignment.assigned_to_driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.logistics_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.recycler_organization),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.driver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.receiver),
                selectinload(LogisticsAssignment.delivery).selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --------------------------------------------------------------------------
    # Delivery Queries
    # --------------------------------------------------------------------------

    async def create_delivery(self, delivery: Delivery) -> Delivery:
        """Persist a new physical delivery record."""
        self.session.add(delivery)
        await self.session.flush()
        await self.session.refresh(delivery)
        return delivery

    async def get_delivery_by_id(self, delivery_id: uuid.UUID) -> Optional[Delivery]:
        """Fetch delivery by ID with full relations."""
        stmt = (
            select(Delivery)
            .where(Delivery.id == delivery_id)
            .options(
                selectinload(Delivery.assignment),
                selectinload(Delivery.recovery),
                selectinload(Delivery.logistics_organization),
                selectinload(Delivery.recycler_organization),
                selectinload(Delivery.driver),
                selectinload(Delivery.receiver),
                selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_delivery_by_assignment_id(
        self, assignment_id: uuid.UUID
    ) -> Optional[Delivery]:
        """Fetch delivery linked to an assignment."""
        stmt = (
            select(Delivery)
            .where(Delivery.assignment_id == assignment_id)
            .options(
                selectinload(Delivery.assignment),
                selectinload(Delivery.recovery),
                selectinload(Delivery.logistics_organization),
                selectinload(Delivery.recycler_organization),
                selectinload(Delivery.driver),
                selectinload(Delivery.receiver),
                selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_delivery_by_recovery_id(
        self, recovery_id: uuid.UUID
    ) -> Optional[Delivery]:
        """Fetch delivery linked to a recovery event."""
        stmt = (
            select(Delivery)
            .where(Delivery.recovery_id == recovery_id)
            .order_by(Delivery.created_at.desc())
            .options(
                selectinload(Delivery.assignment),
                selectinload(Delivery.recovery),
                selectinload(Delivery.logistics_organization),
                selectinload(Delivery.recycler_organization),
                selectinload(Delivery.driver),
                selectinload(Delivery.receiver),
                selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_deliveries(
        self,
        logistics_org_id: Optional[uuid.UUID] = None,
        recycler_org_id: Optional[uuid.UUID] = None,
        status: Optional[DeliveryStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Delivery]:
        """List deliveries filtered by logistics org, recycler org, or status."""
        stmt = select(Delivery)

        if logistics_org_id and recycler_org_id:
            stmt = stmt.where(
                or_(
                    Delivery.logistics_organization_id == logistics_org_id,
                    Delivery.recycler_organization_id == recycler_org_id,
                )
            )
        elif logistics_org_id:
            stmt = stmt.where(Delivery.logistics_organization_id == logistics_org_id)
        elif recycler_org_id:
            stmt = stmt.where(Delivery.recycler_organization_id == recycler_org_id)

        if status:
            stmt = stmt.where(Delivery.status == status)

        stmt = (
            stmt.order_by(Delivery.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(Delivery.assignment),
                selectinload(Delivery.recovery),
                selectinload(Delivery.logistics_organization),
                selectinload(Delivery.recycler_organization),
                selectinload(Delivery.driver),
                selectinload(Delivery.receiver),
                selectinload(Delivery.evidence_records).selectinload(DeliveryEvidence.uploader),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --------------------------------------------------------------------------
    # Evidence Queries
    # --------------------------------------------------------------------------

    async def create_delivery_evidence(
        self, evidence: DeliveryEvidence
    ) -> DeliveryEvidence:
        """Persist a delivery evidence record."""
        self.session.add(evidence)
        await self.session.flush()
        await self.session.refresh(evidence)
        return evidence

    async def list_delivery_evidence(
        self, delivery_id: uuid.UUID
    ) -> List[DeliveryEvidence]:
        """List all digital proof files for a delivery."""
        stmt = (
            select(DeliveryEvidence)
            .where(DeliveryEvidence.delivery_id == delivery_id)
            .order_by(DeliveryEvidence.created_at.asc())
            .options(
                selectinload(DeliveryEvidence.uploader),
                selectinload(DeliveryEvidence.evidence),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
