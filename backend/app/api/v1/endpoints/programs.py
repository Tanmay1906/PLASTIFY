"""PLASTIFY Corporate Recovery Programs API Endpoints.

Implements program creation, metadata updates, status transitions,
and operational partner assignments.
"""

from typing import List
import uuid
from fastapi import APIRouter, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    ProgramServiceDep,
    RequestIDDep,
)
from app.schemas.common import APIResponse
from app.schemas.program import (
    ProgramCreateRequest,
    ProgramPartnerAssignRequest,
    ProgramPartnerResponse,
    ProgramResponse,
    ProgramUpdateRequest,
)

router = APIRouter(prefix="/programs", tags=["Corporate Programs"])


@router.post(
    "",
    response_model=ProgramResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Plastic Recovery Program",
    description="Corporate brand owner launches a new plastic recovery program.",
)
async def create_program(
    data: ProgramCreateRequest,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
) -> ProgramResponse:
    """Create a new corporate program."""
    return await service.create_program(data=data, creator=current_user)


@router.get(
    "",
    response_model=List[ProgramResponse],
    summary="List Recovery Programs",
    description="List programs. Corporates see their own; Super Admins see all; Collectors see assigned programs.",
)
async def list_programs(
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[ProgramResponse]:
    """List recovery programs."""
    return await service.list_programs(requester=current_user, skip=skip, limit=limit)


@router.get(
    "/{program_id}",
    response_model=ProgramResponse,
    summary="Get Program Details",
    description="Retrieve details and recovery progress for a specific program.",
)
async def get_program(
    program_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
) -> ProgramResponse:
    """Get program by ID."""
    return await service.get_program(program_id=program_id, requester=current_user)


@router.patch(
    "/{program_id}",
    response_model=ProgramResponse,
    summary="Update Program",
    description="Update program targets, dates, allowed materials, or status. Restricted to Corporate owner.",
)
async def update_program(
    program_id: uuid.UUID,
    data: ProgramUpdateRequest,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
) -> ProgramResponse:
    """Update program by ID."""
    return await service.update_program(
        program_id=program_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# Operational Partner Assignments
# ------------------------------------------------------------------------------

@router.get(
    "/{program_id}/partners",
    response_model=List[ProgramPartnerResponse],
    summary="List Assigned Program Partners",
    description="List operational partner organizations assigned to execute this program.",
)
async def list_program_partners(
    program_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
) -> List[ProgramPartnerResponse]:
    """List assigned partners for a program."""
    return await service.list_partners(program_id=program_id, requester=current_user)


@router.post(
    "/{program_id}/partners",
    response_model=ProgramPartnerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign Operational Partner",
    description="Assign a Collector or Logistics partner organization to execute collections for this program.",
)
async def assign_program_partner(
    program_id: uuid.UUID,
    data: ProgramPartnerAssignRequest,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
) -> ProgramPartnerResponse:
    """Assign partner organization to program."""
    return await service.assign_partner(
        program_id=program_id, data=data, requester=current_user
    )


@router.delete(
    "/{program_id}/partners/{partner_org_id}",
    response_model=APIResponse[dict],
    summary="Remove Partner from Program",
    description="Remove an operational partner organization from the program.",
)
async def remove_program_partner(
    program_id: uuid.UUID,
    partner_org_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ProgramServiceDep,
    request_id: RequestIDDep,
) -> APIResponse[dict]:
    """Remove partner organization from program."""
    await service.remove_partner(
        program_id=program_id, partner_org_id=partner_org_id, requester=current_user
    )
    return APIResponse(
        data={"message": "Partner organization removed from program successfully."},
        request_id=request_id,
    )
