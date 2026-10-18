"""PLASTIFY Program and Program Partner Data Access Repositories."""

from typing import List, Optional
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.program import Program, ProgramPartner, ProgramStatus
from app.repositories.base import BaseRepository


class ProgramRepository(BaseRepository[Program]):
    """Data access repository for Corporate Plastic Recovery Programs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Program, session)

    async def get_with_organization(self, program_id: uuid.UUID) -> Optional[Program]:
        """Fetch program with eager-loaded organization."""
        stmt = (
            select(Program)
            .where(Program.id == program_id)
            .options(selectinload(Program.organization))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_organization(
        self, organization_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Program]:
        """Fetch all programs created by a corporate organization."""
        stmt = (
            select(Program)
            .where(Program.organization_id == organization_id)
            .options(selectinload(Program.organization))
            .order_by(Program.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, skip: int = 0, limit: int = 100) -> List[Program]:
        """Fetch all active programs."""
        stmt = (
            select(Program)
            .where(Program.status == ProgramStatus.ACTIVE)
            .options(selectinload(Program.organization))
            .order_by(Program.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_collected_weight(
        self, program_id: uuid.UUID, weight_delta_kg: float
    ) -> None:
        """Atomically increment or decrement collected weight for a program."""
        stmt = (
            update(Program)
            .where(Program.id == program_id)
            .values(collected_kg=Program.collected_kg + weight_delta_kg)
        )
        await self.session.execute(stmt)
        await self.session.flush()


class ProgramPartnerRepository(BaseRepository[ProgramPartner]):
    """Data access repository for Program Partner assignments."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ProgramPartner, session)

    async def get_assignment(
        self, program_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Optional[ProgramPartner]:
        """Check if an organization is assigned to a program."""
        stmt = (
            select(ProgramPartner)
            .where(
                ProgramPartner.program_id == program_id,
                ProgramPartner.organization_id == organization_id,
            )
            .options(selectinload(ProgramPartner.organization))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_program(self, program_id: uuid.UUID) -> List[ProgramPartner]:
        """Fetch all assigned partner organizations for a program."""
        stmt = (
            select(ProgramPartner)
            .where(ProgramPartner.program_id == program_id)
            .options(selectinload(ProgramPartner.organization))
            .order_by(ProgramPartner.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_partner_org(
        self, organization_id: uuid.UUID
    ) -> List[ProgramPartner]:
        """Fetch all program assignments for a specific partner organization."""
        stmt = (
            select(ProgramPartner)
            .where(
                ProgramPartner.organization_id == organization_id,
                ProgramPartner.is_active == True,  # noqa: E712
            )
            .options(selectinload(ProgramPartner.program))
            .order_by(ProgramPartner.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def is_partner_assigned(
        self, program_id: uuid.UUID, organization_id: uuid.UUID
    ) -> bool:
        """Check if organization is an active assigned partner on the program."""
        assignment = await self.get_assignment(program_id, organization_id)
        return assignment is not None and assignment.is_active
