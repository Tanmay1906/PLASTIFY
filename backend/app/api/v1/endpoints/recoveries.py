"""PLASTIFY Plastic Collection & Recovery API Endpoints.

Implements recovery event creation, draft updates, official submission,
and immutable state transition audit retrieval.
"""

from typing import List
import uuid
from fastapi import APIRouter, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    ProgramServiceDep,
    RecoveryServiceDep,
)
from app.schemas.program import ProgramResponse
from app.schemas.recovery import (
    RecoveryCreateRequest,
    RecoveryHistoryResponse,
    RecoveryResponse,
    RecoverySubmitRequest,
    RecoveryUpdateRequest,
)

router = APIRouter(prefix="/recoveries", tags=["Collection & Recovery Engine"])


@router.post(
    "",
    response_model=RecoveryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Recovery Event",
    description="Authorized Collector logs a recovery event. The backend atomically generates an immutable Recovery ID.",
)
async def create_recovery(
    data: RecoveryCreateRequest,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
) -> RecoveryResponse:
    """Create a new plastic recovery event in DRAFT status."""
    return await service.create_recovery(data=data, collector=current_user)


@router.get(
    "/collector/me",
    response_model=List[RecoveryResponse],
    summary="List Collector Recoveries",
    description="List all recovery events logged by the authenticated collector or their organization.",
)
async def list_my_recoveries(
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[RecoveryResponse]:
    """List recovery events for the current collector."""
    return await service.list_collector_recoveries(
        collector_id=current_user.id, requester=current_user, skip=skip, limit=limit
    )


@router.get(
    "/collector/tasks",
    response_model=List[ProgramResponse],
    summary="List Assigned Collection Tasks",
    description="List active recovery programs assigned to the authenticated collector's organization.",
)
async def list_collector_tasks(
    current_user: CurrentUserDep,
    program_service: ProgramServiceDep,
) -> List[ProgramResponse]:
    """Collector view assigned collection tasks."""
    return await program_service.list_programs(requester=current_user)


@router.get(
    "/program/{program_id}",
    response_model=List[RecoveryResponse],
    summary="List Program Recoveries",
    description="List all recovery events submitted under a specific corporate program.",
)
async def list_program_recoveries(
    program_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[RecoveryResponse]:
    """List recoveries for a program."""
    return await service.list_program_recoveries(
        program_id=program_id, requester=current_user, skip=skip, limit=limit
    )


@router.get(
    "/{identifier}",
    response_model=RecoveryResponse,
    summary="Get Recovery Event Details",
    description="Retrieve recovery details, material specifications, and full state transition history by UUID or human Recovery ID.",
)
async def get_recovery(
    identifier: str,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
) -> RecoveryResponse:
    """Get recovery event by UUID or human-readable recovery ID (e.g. POP-DEL-2026-000184)."""
    return await service.get_recovery(identifier=identifier, requester=current_user)


@router.patch(
    "/{event_id}",
    response_model=RecoveryResponse,
    summary="Update Draft Recovery Event",
    description="Update weight, material, or location on an unsubmitted DRAFT recovery event.",
)
async def update_draft_recovery(
    event_id: uuid.UUID,
    data: RecoveryUpdateRequest,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
) -> RecoveryResponse:
    """Update draft recovery event."""
    return await service.update_draft_recovery(
        event_id=event_id, data=data, collector=current_user
    )


@router.post(
    "/{event_id}/submit",
    response_model=RecoveryResponse,
    summary="Submit Recovery Event",
    description="Lock draft recovery event, transition status to SUBMITTED, update program progress, and record audit history.",
)
async def submit_recovery(
    event_id: uuid.UUID,
    data: RecoverySubmitRequest,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
) -> RecoveryResponse:
    """Submit recovery event."""
    return await service.submit_recovery(
        event_id=event_id, data=data, collector=current_user
    )


@router.get(
    "/{event_id}/history",
    response_model=List[RecoveryHistoryResponse],
    summary="Get Recovery Event State Transition History",
    description="Retrieve the immutable chronological audit log of state transitions for a recovery event.",
)
async def get_recovery_history(
    event_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: RecoveryServiceDep,
) -> List[RecoveryHistoryResponse]:
    """Get immutable event history."""
    return await service.get_recovery_history(event_id=event_id, requester=current_user)
