"""PLASTIFY Organization, Member, and Partner Service Layer.

Enforces strict tenant isolation, prevents IDOR/BOLA cross-organization data leakage,
and coordinates organization lifecycles and partnerships.
"""

import re
from typing import List, Optional
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.organization import (
    Organization,
    OrganizationMember,
    OrgMemberRole,
    PartnerRelationship,
    PartnerStatus,
)
from app.models.user import User, UserRole
from app.repositories.organization import (
    OrganizationRepository,
    OrgMemberRepository,
    PartnerRepository,
)
from app.repositories.user import UserRepository
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgMemberAddRequest,
    OrgMemberResponse,
    OrgMemberUpdateRequest,
    PartnerCreateRequest,
    PartnerResponse,
)
from app.services.base import BaseService


class OrganizationService(BaseService):
    """Business service governing organizations, memberships, and partner networks."""

    def __init__(
        self,
        settings: Settings,
        org_repo: OrganizationRepository,
        member_repo: OrgMemberRepository,
        partner_repo: PartnerRepository,
        user_repo: UserRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.org_repo = org_repo
        self.member_repo = member_repo
        self.partner_repo = partner_repo
        self.user_repo = user_repo

    # --------------------------------------------------------------------------
    # Organization CRUD
    # --------------------------------------------------------------------------

    async def create_organization(
        self, data: OrganizationCreateRequest, creator: User
    ) -> OrganizationResponse:
        """Create a new organization and assign the creator as Org Admin."""
        # Check name uniqueness
        existing = await self.org_repo.get_by_name(data.name)
        if existing:
            raise ConflictException(f"Organization '{data.name}' already exists.")

        slug = self._generate_slug(data.name)
        # Ensure slug uniqueness
        counter = 1
        base_slug = slug
        while await self.org_repo.get_by_slug(slug):
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization(
            name=data.name.strip(),
            slug=slug,
            org_type=data.org_type,
            contact_email=data.contact_email.strip().lower(),
            country=data.country.strip(),
            city=data.city.strip() if data.city else None,
            address=data.address,
            registration_number=data.registration_number,
            tax_id=data.tax_id,
            contact_phone=data.contact_phone,
            website=data.website,
            description=data.description,
            is_active=True,
            is_verified=False,
        )
        created_org = await self.org_repo.create(org)

        # Creator automatically becomes Admin member of this organization
        membership = OrganizationMember(
            organization_id=created_org.id,
            user_id=creator.id,
            role=OrgMemberRole.ADMIN,
            is_active=True,
        )
        await self.member_repo.create(membership)

        # Set creator's primary organization if not already set
        if creator.organization_id is None:
            creator.organization_id = created_org.id
            await self.user_repo.session.flush()

        self.logger.info(
            f"Organization created: {created_org.name} (type: {created_org.org_type.value}) by {creator.email}"
        )
        return OrganizationResponse.model_validate(created_org)

    async def get_organization(
        self, org_id: uuid.UUID, requester: User
    ) -> OrganizationResponse:
        """Retrieve organization profile with strict cross-organization authorization checks."""
        # Enforce IDOR protection: Super Admin can access all; others can only access their org
        await self._assert_org_access(org_id, requester)

        org = await self.org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException("Organization not found.")

        return OrganizationResponse.model_validate(org)

    async def update_organization(
        self, org_id: uuid.UUID, data: OrganizationUpdateRequest, requester: User
    ) -> OrganizationResponse:
        """Update organization profile. Only Super Admin or Org Admin allowed."""
        await self._assert_org_admin(org_id, requester)

        org = await self.org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException("Organization not found.")

        update_data = data.model_dump(exclude_unset=True)
        if "name" in update_data and update_data["name"] != org.name:
            existing = await self.org_repo.get_by_name(update_data["name"])
            if existing and existing.id != org.id:
                raise ConflictException("Organization with this name already exists.")
            org.name = update_data["name"]

        for field, value in update_data.items():
            if field != "name" and hasattr(org, field):
                setattr(org, field, value)

        await self.org_repo.session.flush()
        self.logger.info(f"Organization {org.name} updated by {requester.email}")
        return OrganizationResponse.model_validate(org)

    async def list_organizations(
        self, requester: User, skip: int = 0, limit: int = 50
    ) -> List[OrganizationResponse]:
        """List organizations.

        SUPER_ADMIN can list all organizations.
        Regular users only receive their own organization to prevent cross-tenant harvesting.
        """
        if requester.role == UserRole.SUPER_ADMIN:
            orgs = await self.org_repo.list(skip=skip, limit=limit)
            return [OrganizationResponse.model_validate(o) for o in orgs]

        # Regular user: return their assigned organization if present
        if requester.organization_id:
            org = await self.org_repo.get_by_id(requester.organization_id)
            if org:
                return [OrganizationResponse.model_validate(org)]

        return []

    # --------------------------------------------------------------------------
    # Membership Management
    # --------------------------------------------------------------------------

    async def add_member(
        self, org_id: uuid.UUID, data: OrgMemberAddRequest, requester: User
    ) -> OrgMemberResponse:
        """Add or invite a user to the organization. Org Admin or Super Admin required."""
        await self._assert_org_admin(org_id, requester)

        # Find target user by ID or Email
        target_user: Optional[User] = None
        if data.user_id:
            target_user = await self.user_repo.get_by_id(data.user_id)
        elif data.email:
            target_user = await self.user_repo.get_by_email(data.email)

        if not target_user:
            raise NotFoundException("User not found.")

        # Check if already a member
        existing_member = await self.member_repo.get_membership(org_id, target_user.id)
        if existing_member:
            raise ConflictException("User is already a member of this organization.")

        membership = OrganizationMember(
            organization_id=org_id,
            user_id=target_user.id,
            role=data.role,
            is_active=True,
        )
        created_member = await self.member_repo.create(membership)

        # Set user's organization_id if unset
        if target_user.organization_id is None:
            target_user.organization_id = org_id
            await self.user_repo.session.flush()

        self.logger.info(
            f"Added {target_user.email} to org {org_id} with role {data.role} by {requester.email}"
        )
        return OrgMemberResponse(
            id=created_member.id,
            organization_id=created_member.organization_id,
            user_id=created_member.user_id,
            role=created_member.role,
            is_active=created_member.is_active,
            created_at=created_member.created_at,
            user_email=target_user.email,
            user_name=target_user.full_name,
        )

    async def update_member(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        data: OrgMemberUpdateRequest,
        requester: User,
    ) -> OrgMemberResponse:
        """Modify role or activation state of an organization member."""
        await self._assert_org_admin(org_id, requester)

        member = await self.member_repo.get_membership(org_id, user_id)
        if not member:
            raise NotFoundException("Member not found in this organization.")

        if data.role is not None:
            member.role = data.role
        if data.is_active is not None:
            member.is_active = data.is_active

        await self.member_repo.session.flush()
        user = await self.user_repo.get_by_id(user_id)

        return OrgMemberResponse(
            id=member.id,
            organization_id=member.organization_id,
            user_id=member.user_id,
            role=member.role,
            is_active=member.is_active,
            created_at=member.created_at,
            user_email=user.email if user else None,
            user_name=user.full_name if user else None,
        )

    async def remove_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, requester: User
    ) -> None:
        """Remove a user from the organization."""
        await self._assert_org_admin(org_id, requester)

        member = await self.member_repo.get_membership(org_id, user_id)
        if not member:
            raise NotFoundException("Member not found in this organization.")

        await self.member_repo.delete(member)

        # Clear user primary organization if matching
        user = await self.user_repo.get_by_id(user_id)
        if user and user.organization_id == org_id:
            user.organization_id = None
            await self.user_repo.session.flush()

        self.logger.info(f"Removed user {user_id} from org {org_id} by {requester.email}")

    async def list_members(
        self, org_id: uuid.UUID, requester: User, skip: int = 0, limit: int = 100
    ) -> List[OrgMemberResponse]:
        """List members of an organization with IDOR protection."""
        await self._assert_org_access(org_id, requester)

        members = await self.member_repo.list_by_org(org_id, skip=skip, limit=limit)
        results = []
        for m in members:
            results.append(
                OrgMemberResponse(
                    id=m.id,
                    organization_id=m.organization_id,
                    user_id=m.user_id,
                    role=m.role,
                    is_active=m.is_active,
                    created_at=m.created_at,
                    user_email=m.user.email if m.user else None,
                    user_name=m.user.full_name if m.user else None,
                )
            )
        return results

    # --------------------------------------------------------------------------
    # Partner Relationships
    # --------------------------------------------------------------------------

    async def create_partner_request(
        self, org_id: uuid.UUID, data: PartnerCreateRequest, requester: User
    ) -> PartnerResponse:
        """Propose a partner agreement between two organizations."""
        await self._assert_org_admin(org_id, requester)

        if org_id == data.partner_org_id:
            raise BadRequestException("An organization cannot partner with itself.")

        partner_org = await self.org_repo.get_by_id(data.partner_org_id)
        if not partner_org or not partner_org.is_active:
            raise NotFoundException("Target partner organization does not exist or is inactive.")

        existing = await self.partner_repo.get_relationship(org_id, data.partner_org_id)
        if existing:
            raise ConflictException(
                f"A partnership agreement between these organizations already exists (Status: {existing.status.value})."
            )

        relationship = PartnerRelationship(
            initiator_org_id=org_id,
            partner_org_id=data.partner_org_id,
            relationship_type=data.relationship_type,
            status=PartnerStatus.PENDING,
            notes=data.notes,
        )
        created = await self.partner_repo.create(relationship)

        initiator = await self.org_repo.get_by_id(org_id)

        return PartnerResponse(
            id=created.id,
            initiator_org_id=created.initiator_org_id,
            partner_org_id=created.partner_org_id,
            relationship_type=created.relationship_type,
            status=created.status,
            notes=created.notes,
            created_at=created.created_at,
            updated_at=created.updated_at,
            initiator_name=initiator.name if initiator else None,
            partner_name=partner_org.name,
        )

    async def update_partner_status(
        self,
        org_id: uuid.UUID,
        relationship_id: uuid.UUID,
        new_status: PartnerStatus,
        requester: User,
    ) -> PartnerResponse:
        """Update partnership agreement status (accept, reject, terminate)."""
        rel = await self.partner_repo.get_by_id(relationship_id)
        if not rel:
            raise NotFoundException("Partner agreement record not found.")

        # Ensure agreement belongs to this org
        if rel.initiator_org_id != org_id and rel.partner_org_id != org_id:
            raise ForbiddenException("Access denied: Agreement does not belong to this organization.")

        # Requester must be admin of org_id or Super Admin
        await self._assert_org_admin(org_id, requester)

        rel.status = new_status
        await self.partner_repo.session.flush()

        initiator = await self.org_repo.get_by_id(rel.initiator_org_id)
        partner = await self.org_repo.get_by_id(rel.partner_org_id)

        return PartnerResponse(
            id=rel.id,
            initiator_org_id=rel.initiator_org_id,
            partner_org_id=rel.partner_org_id,
            relationship_type=rel.relationship_type,
            status=rel.status,
            notes=rel.notes,
            created_at=rel.created_at,
            updated_at=rel.updated_at,
            initiator_name=initiator.name if initiator else None,
            partner_name=partner.name if partner else None,
        )

    async def list_partnerships(
        self, org_id: uuid.UUID, requester: User
    ) -> List[PartnerResponse]:
        """List partner agreements for an organization."""
        await self._assert_org_access(org_id, requester)

        relationships = await self.partner_repo.list_for_org(org_id)
        results = []
        for rel in relationships:
            results.append(
                PartnerResponse(
                    id=rel.id,
                    initiator_org_id=rel.initiator_org_id,
                    partner_org_id=rel.partner_org_id,
                    relationship_type=rel.relationship_type,
                    status=rel.status,
                    notes=rel.notes,
                    created_at=rel.created_at,
                    updated_at=rel.updated_at,
                    initiator_name=rel.initiator_org.name if rel.initiator_org else None,
                    partner_name=rel.partner_org.name if rel.partner_org else None,
                )
            )
        return results

    # --------------------------------------------------------------------------
    # Authorization Helpers (IDOR & Tenant Isolation Safeguards)
    # --------------------------------------------------------------------------

    async def _assert_org_access(self, org_id: uuid.UUID, user: User) -> None:
        """Enforce that user has legitimate authorization to access this organization's data."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if user.organization_id == org_id:
            return

        is_member = await self.member_repo.is_member(org_id, user.id)
        if not is_member:
            raise ForbiddenException(
                "Access denied: You do not have permission to access another organization's private data."
            )

    async def _assert_org_admin(self, org_id: uuid.UUID, user: User) -> None:
        """Enforce that user has administrative authority over the specified organization."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        is_admin = await self.member_repo.is_org_admin(org_id, user.id)
        if not is_admin:
            raise ForbiddenException(
                "Access denied: Administrator privileges required for this organization."
            )

    def _generate_slug(self, name: str) -> str:
        """Generate URL-safe slug from organization name."""
        s = re.sub(r"[^\w\s-]", "", name.lower())
        return re.sub(r"[-\s]+", "-", s).strip("-")
