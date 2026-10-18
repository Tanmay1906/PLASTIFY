"""PLASTIFY Chain-of-Custody API Endpoints.

Provides endpoints to advance circular materials along the chain-of-custody
and retrieve the immutable chronological audit timeline for any recovery event.
"""

import uuid
from fastapi import APIRouter, status

from app.core.dependencies import (
    CurrentUserDep,
    CustodyServiceDep,
)
from app.schemas.custody import (
    CustodyTimelineResponse,
    CustodyTransitionRequest,
)

router = APIRouter(prefix="/recoveries", tags=["Chain of Custody"])


@router.post(
    "/{recovery_id}/custody/transition",
    response_model=CustodyTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition Chain of Custody Milestone",
    description=(
        "Advance material through circular milestones (CREATED, SUBMITTED, PICKUP_ASSIGNED, "
        "PICKED_UP, IN_TRANSIT, DELIVERED, RECEIVED, VERIFIED, PROCESSED, REJECTED). "
        "Enforces strict role permissions and records an immutable audit log entry."
    ),
)
async def transition_custody(
    recovery_id: uuid.UUID,
    data: CustodyTransitionRequest,
    current_user: CurrentUserDep,
    service: CustodyServiceDep,
) -> CustodyTimelineResponse:
    """Transition recovery event along the chain-of-custody."""
    return await service.transition_custody(
        recovery_id=recovery_id, data=data, actor=current_user
    )


@router.get(
    "/{recovery_id}/custody",
    response_model=CustodyTimelineResponse,
    summary="Get Chain of Custody Timeline",
    description="Retrieve the complete, tamper-proof chronological history of all custody transitions.",
)
async def get_custody_timeline(
    recovery_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: CustodyServiceDep,
) -> CustodyTimelineResponse:
    """Retrieve immutable chain-of-custody timeline for a recovery event."""
    return await service.get_custody_timeline(
        recovery_id=recovery_id, requester=current_user
    )
