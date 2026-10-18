"""PLASTIFY Impact Ledger, Methodology, and Eligibility Assessment Repositories."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.impact import (
    AssessmentStatus,
    EligibilityAssessment,
    ImpactAllocation,
    ImpactOutcomeType,
    ImpactRecord,
    ImpactStatus,
    Methodology,
    MethodologyVersion,
)
from app.repositories.base import BaseRepository


class ImpactRepository(BaseRepository[ImpactRecord]):
    """Data access repository for verified physical impact records and allocations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ImpactRecord, session)

    async def get_by_id(self, impact_id: uuid.UUID) -> Optional[ImpactRecord]:
        """Fetch impact record by primary key with all associations loaded."""
        stmt = (
            select(ImpactRecord)
            .where(ImpactRecord.id == impact_id)
            .options(
                selectinload(ImpactRecord.organization),
                selectinload(ImpactRecord.program),
                selectinload(ImpactRecord.source_recovery),
                selectinload(ImpactRecord.source_material_batch),
                selectinload(ImpactRecord.source_upcycling_batch),
                selectinload(ImpactRecord.verification_record),
                selectinload(ImpactRecord.allocations),
                selectinload(ImpactRecord.assessments),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_for_update(self, impact_id: uuid.UUID) -> Optional[ImpactRecord]:
        """Fetch impact record with exclusive row lock to protect concurrency."""
        stmt = (
            select(ImpactRecord)
            .where(ImpactRecord.id == impact_id)
            .with_for_update()
            .options(
                selectinload(ImpactRecord.organization),
                selectinload(ImpactRecord.program),
                selectinload(ImpactRecord.source_recovery),
                selectinload(ImpactRecord.source_material_batch),
                selectinload(ImpactRecord.allocations),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_impact_id(self, code: str) -> Optional[ImpactRecord]:
        """Fetch impact record by unique code (e.g. IMP-2026-COL-000001)."""
        stmt = (
            select(ImpactRecord)
            .where(ImpactRecord.impact_id == code.strip().upper())
            .options(
                selectinload(ImpactRecord.organization),
                selectinload(ImpactRecord.program),
                selectinload(ImpactRecord.source_recovery),
                selectinload(ImpactRecord.source_material_batch),
                selectinload(ImpactRecord.allocations),
                selectinload(ImpactRecord.assessments),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_source_recovery_id(self, recovery_id: uuid.UUID) -> Optional[ImpactRecord]:
        """Check if an active impact record already exists for a recovery event."""
        stmt = (
            select(ImpactRecord)
            .where(
                ImpactRecord.source_recovery_id == recovery_id,
                ImpactRecord.status != ImpactStatus.REVOKED,
                ImpactRecord.status != ImpactStatus.SUPERSEDED,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_source_material_batch_id(self, batch_id: uuid.UUID) -> Optional[ImpactRecord]:
        """Check if an active impact record already exists for a recycling material batch."""
        stmt = (
            select(ImpactRecord)
            .where(
                ImpactRecord.source_material_batch_id == batch_id,
                ImpactRecord.status != ImpactStatus.REVOKED,
                ImpactRecord.status != ImpactStatus.SUPERSEDED,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_impacts(
        self,
        organization_id: Optional[uuid.UUID] = None,
        outcome_type: Optional[ImpactOutcomeType] = None,
        status: Optional[ImpactStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[ImpactRecord]:
        """List impact records with tenant filtering and pagination."""
        stmt = select(ImpactRecord)
        if organization_id:
            stmt = stmt.where(ImpactRecord.organization_id == organization_id)
        if outcome_type:
            stmt = stmt.where(ImpactRecord.outcome_type == outcome_type)
        if status:
            stmt = stmt.where(ImpactRecord.status == status)

        stmt = (
            stmt.options(
                selectinload(ImpactRecord.organization),
                selectinload(ImpactRecord.program),
                selectinload(ImpactRecord.allocations),
            )
            .order_by(ImpactRecord.recorded_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_impacts(
        self,
        organization_id: Optional[uuid.UUID] = None,
        outcome_type: Optional[ImpactOutcomeType] = None,
        status: Optional[ImpactStatus] = None,
    ) -> int:
        """Count total matching impact records."""
        stmt = select(func.count(ImpactRecord.id))
        if organization_id:
            stmt = stmt.where(ImpactRecord.organization_id == organization_id)
        if outcome_type:
            stmt = stmt.where(ImpactRecord.outcome_type == outcome_type)
        if status:
            stmt = stmt.where(ImpactRecord.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def get_allocated_quantity(self, impact_id: uuid.UUID) -> Decimal:
        """Calculate authoritative sum of allocated quantity directly from DB allocations."""
        stmt = select(func.coalesce(func.sum(ImpactAllocation.allocated_quantity), 0.0)).where(
            ImpactAllocation.impact_record_id == impact_id
        )
        res = await self.session.execute(stmt)
        val = res.scalar_one()
        return Decimal(str(val))

    async def create_allocation(self, allocation: ImpactAllocation) -> ImpactAllocation:
        """Persist a new impact allocation."""
        self.session.add(allocation)
        await self.session.flush()
        return allocation

    async def generate_next_impact_id(self, outcome_type: ImpactOutcomeType, year: int) -> str:
        """Generate unique human-readable impact code (e.g. IMP-2026-COL-F8B2A1)."""
        prefix_map = {
            ImpactOutcomeType.COLLECTION: "COL",
            ImpactOutcomeType.DELIVERY: "DEL",
            ImpactOutcomeType.RECYCLING_INPUT: "RIN",
            ImpactOutcomeType.RECYCLED_OUTPUT: "REC",
            ImpactOutcomeType.UPCYCLED_PRODUCT: "UPC",
            ImpactOutcomeType.RESIDUE: "RES",
        }
        type_prefix = prefix_map.get(outcome_type, "IMP")
        unique_suffix = uuid.uuid4().hex[:8].upper()
        return f"IMP-{year}-{type_prefix}-{unique_suffix}"


class MethodologyRepository(BaseRepository[Methodology]):
    """Data access repository for methodologies and version specifications."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Methodology, session)

    async def get_by_id(self, id_val: uuid.UUID) -> Optional[Methodology]:
        """Fetch methodology by UUID with all versions."""
        stmt = (
            select(Methodology)
            .where(Methodology.id == id_val)
            .options(selectinload(Methodology.versions))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_code(self, code: str) -> Optional[Methodology]:
        """Fetch methodology by unique code."""
        stmt = (
            select(Methodology)
            .where(Methodology.code == code.strip().upper())
            .options(selectinload(Methodology.versions))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_active(self) -> List[Methodology]:
        """List all active methodologies."""
        stmt = (
            select(Methodology)
            .where(Methodology.is_active.is_(True))
            .options(selectinload(Methodology.versions))
            .order_by(Methodology.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_version_by_id(self, version_id: uuid.UUID) -> Optional[MethodologyVersion]:
        """Fetch methodology version by UUID."""
        stmt = (
            select(MethodologyVersion)
            .where(MethodologyVersion.id == version_id)
            .options(selectinload(MethodologyVersion.methodology))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_version_by_tag(
        self, methodology_id: uuid.UUID, version_tag: str
    ) -> Optional[MethodologyVersion]:
        """Fetch specific version tag under a methodology."""
        stmt = (
            select(MethodologyVersion)
            .where(
                MethodologyVersion.methodology_id == methodology_id,
                MethodologyVersion.version_tag == version_tag.strip(),
            )
            .options(selectinload(MethodologyVersion.methodology))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_version(self, version: MethodologyVersion) -> MethodologyVersion:
        """Persist a new immutable methodology version."""
        self.session.add(version)
        await self.session.flush()
        return version


class AssessmentRepository(BaseRepository[EligibilityAssessment]):
    """Data access repository for credit eligibility assessments."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(EligibilityAssessment, session)

    async def get_by_id(self, assessment_id: uuid.UUID) -> Optional[EligibilityAssessment]:
        """Fetch assessment by primary key."""
        stmt = (
            select(EligibilityAssessment)
            .where(EligibilityAssessment.id == assessment_id)
            .options(
                selectinload(EligibilityAssessment.impact_record).selectinload(ImpactRecord.organization),
                selectinload(EligibilityAssessment.methodology_version).selectinload(MethodologyVersion.methodology),
                selectinload(EligibilityAssessment.assessor),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_number(self, assessment_number: str) -> Optional[EligibilityAssessment]:
        """Fetch assessment by human-readable assessment code."""
        stmt = (
            select(EligibilityAssessment)
            .where(EligibilityAssessment.assessment_number == assessment_number.strip().upper())
            .options(
                selectinload(EligibilityAssessment.impact_record),
                selectinload(EligibilityAssessment.methodology_version),
                selectinload(EligibilityAssessment.assessor),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_impact_record(self, impact_record_id: uuid.UUID) -> List[EligibilityAssessment]:
        """List all assessments run against a specific impact record."""
        stmt = (
            select(EligibilityAssessment)
            .where(EligibilityAssessment.impact_record_id == impact_record_id)
            .options(
                selectinload(EligibilityAssessment.methodology_version),
                selectinload(EligibilityAssessment.assessor),
            )
            .order_by(EligibilityAssessment.assessed_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_assessments(
        self,
        status: Optional[AssessmentStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[EligibilityAssessment]:
        """List assessments with status filter and pagination."""
        stmt = select(EligibilityAssessment)
        if status:
            stmt = stmt.where(EligibilityAssessment.status == status)
        stmt = (
            stmt.options(
                selectinload(EligibilityAssessment.impact_record),
                selectinload(EligibilityAssessment.methodology_version),
                selectinload(EligibilityAssessment.assessor),
            )
            .order_by(EligibilityAssessment.assessed_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def generate_next_assessment_number(self, year: int) -> str:
        """Generate unique assessment identifier."""
        return f"ASN-{year}-{uuid.uuid4().hex[:8].upper()}"
