"""PLASTIFY Organization Management API Endpoints.

Implements organization registration, profile updates, member management,
and bilateral partnership agreements with cross-tenant IDOR protection.
"""

from typing import List
import uuid
from fastapi import APIRouter, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    OrgServiceDep,
    RequestIDDep,
)
from app.schemas.common import APIResponse
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgMemberAddRequest,
    OrgMemberResponse,
    OrgMemberUpdateRequest,
    PartnerCreateRequest,
    PartnerResponse,
    PartnerUpdateRequest,
)

router = APIRouter(prefix="/organizations", tags=["Organizations & Partnerships"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Organization",
    description="Registers a new circular economy organization. Creator automatically becomes Org Admin.",
)
async def create_organization(
    data: OrganizationCreateRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> OrganizationResponse:
    """Create a new organization."""
    return await service.create_organization(data=data, creator=current_user)


@router.get(
    "",
    response_model=List[OrganizationResponse],
    summary="List Organizations",
    description="Lists organizations. Super Admins view all; other users view their own organization.",
)
async def list_organizations(
    current_user: CurrentUserDep,
    service: OrgServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[OrganizationResponse]:
    """List organizations."""
    return await service.list_organizations(requester=current_user, skip=skip, limit=limit)


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Get Organization Profile",
    description="Retrieves organization profile. Access restricted to members, admins, and Super Admins.",
)
async def get_organization(
    org_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> OrganizationResponse:
    """Get organization by ID."""
    return await service.get_organization(org_id=org_id, requester=current_user)


@router.patch(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Update Organization Profile",
    description="Updates organization details. Restricted to Organization Admins and Super Admins.",
)
async def update_organization(
    org_id: uuid.UUID,
    data: OrganizationUpdateRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> OrganizationResponse:
    """Update organization by ID."""
    return await service.update_organization(
        org_id=org_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# Organization Member Management
# ------------------------------------------------------------------------------

@router.get(
    "/{org_id}/members",
    response_model=List[OrgMemberResponse],
    summary="List Organization Members",
    description="Lists members belonging to this organization. Access restricted to organization members.",
)
async def list_members(
    org_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> List[OrgMemberResponse]:
    """List organization members."""
    return await service.list_members(
        org_id=org_id, requester=current_user, skip=skip, limit=limit
    )


@router.post(
    "/{org_id}/members",
    response_model=OrgMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add/Invite Member",
    description="Adds a user to the organization. Restricted to Org Admins and Super Admins.",
)
async def add_member(
    org_id: uuid.UUID,
    data: OrgMemberAddRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> OrgMemberResponse:
    """Add member to organization."""
    return await service.add_member(
        org_id=org_id, data=data, requester=current_user
    )


@router.patch(
    "/{org_id}/members/{user_id}",
    response_model=OrgMemberResponse,
    summary="Update Member Role or Status",
    description="Modifies an organization member's role or status. Restricted to Org Admins.",
)
async def update_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: OrgMemberUpdateRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> OrgMemberResponse:
    """Update member role or status."""
    return await service.update_member(
        org_id=org_id, user_id=user_id, data=data, requester=current_user
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    response_model=APIResponse[dict],
    summary="Remove Member",
    description="Removes a member from the organization. Restricted to Org Admins and Super Admins.",
)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
    request_id: RequestIDDep,
) -> APIResponse[dict]:
    """Remove member from organization."""
    await service.remove_member(
        org_id=org_id, user_id=user_id, requester=current_user
    )
    return APIResponse(
        data={"message": "Member successfully removed from organization."},
        request_id=request_id,
    )


# ------------------------------------------------------------------------------
# Partner Relationships
# ------------------------------------------------------------------------------

@router.get(
    "/{org_id}/partners",
    response_model=List[PartnerResponse],
    summary="List Organization Partnerships",
    description="Lists bilateral partner relationships. Restricted to organization members.",
)
async def list_partners(
    org_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> List[PartnerResponse]:
    """List partnerships for organization."""
    return await service.list_partnerships(
        org_id=org_id, requester=current_user
    )


@router.post(
    "/{org_id}/partners",
    response_model=PartnerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate Partnership Request",
    description="Proposes a partner agreement with another organization. Restricted to Org Admins.",
)
async def request_partnership(
    org_id: uuid.UUID,
    data: PartnerCreateRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> PartnerResponse:
    """Propose partnership."""
    return await service.create_partner_request(
        org_id=org_id, data=data, requester=current_user
    )


@router.patch(
    "/{org_id}/partners/{partner_id}",
    response_model=PartnerResponse,
    summary="Update Partnership Status",
    description="Accepts, rejects, or terminates a partnership agreement. Restricted to Org Admins.",
)
async def update_partnership_status(
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    data: PartnerUpdateRequest,
    current_user: CurrentUserDep,
    service: OrgServiceDep,
) -> PartnerResponse:
    """Update partnership status."""
    return await service.update_partner_status(
        org_id=org_id,
        relationship_id=partner_id,
        new_status=data.status,
        requester=current_user,
    )
