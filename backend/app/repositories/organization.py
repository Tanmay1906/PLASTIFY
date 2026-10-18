"""PLASTIFY Organization, Member, and Partner Repositories."""

from typing import List, Optional
import uuid
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import (
    Organization,
    OrganizationMember,
    OrgMemberRole,
    PartnerRelationship,
)
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    """Data access repository for Organization entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Organization, session)

    async def get_by_name(self, name: str) -> Optional[Organization]:
        """Fetch organization by name."""
        stmt = select(Organization).where(Organization.name.ilike(name.strip()))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        """Fetch organization by slug."""
        stmt = select(Organization).where(Organization.slug == slug.strip().lower())
        result = await self.session.execute(stmt)
        return result.scalars().first()


class OrgMemberRepository(BaseRepository[OrganizationMember]):
    """Data access repository for Organization Membership records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OrganizationMember, session)

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[OrganizationMember]:
        """Retrieve membership relationship between user and organization."""
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        ).options(selectinload(OrganizationMember.user))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_org(
        self, organization_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[OrganizationMember]:
        """Fetch all members of an organization with eager-loaded user info."""
        stmt = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .options(selectinload(OrganizationMember.user))
            .order_by(OrganizationMember.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def is_member(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Check if user has an active membership in the organization."""
        member = await self.get_membership(organization_id, user_id)
        return member is not None and member.is_active

    async def is_org_admin(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Check if user has ADMIN rights within the organization."""
        member = await self.get_membership(organization_id, user_id)
        return member is not None and member.is_active and member.role == OrgMemberRole.ADMIN


class PartnerRepository(BaseRepository[PartnerRelationship]):
    """Data access repository for bilateral Partner relationships."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PartnerRelationship, session)

    async def get_relationship(
        self, initiator_id: uuid.UUID, partner_id: uuid.UUID
    ) -> Optional[PartnerRelationship]:
        """Fetch specific partner contract between two organizations."""
        stmt = select(PartnerRelationship).where(
            or_(
                (PartnerRelationship.initiator_org_id == initiator_id)
                & (PartnerRelationship.partner_org_id == partner_id),
                (PartnerRelationship.initiator_org_id == partner_id)
                & (PartnerRelationship.partner_org_id == initiator_id),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_org(
        self, organization_id: uuid.UUID
    ) -> List[PartnerRelationship]:
        """Fetch all incoming and outgoing partner agreements for an organization."""
        stmt = (
            select(PartnerRelationship)
            .where(
                or_(
                    PartnerRelationship.initiator_org_id == organization_id,
                    PartnerRelationship.partner_org_id == organization_id,
                )
            )
            .options(
                selectinload(PartnerRelationship.initiator_org),
                selectinload(PartnerRelationship.partner_org),
            )
            .order_by(PartnerRelationship.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
