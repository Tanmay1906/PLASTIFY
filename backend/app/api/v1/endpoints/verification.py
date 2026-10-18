"""PLASTIFY Verification Engine REST Endpoints.

Authoritative verification review queue, full dossier package inspection,
determinations (Approve, Reject, Flag), and audit findings.
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    VerificationServiceDep,
)
from app.models.recovery import RecoveryStatus
from app.schemas.verification import (
    ApproveVerificationRequest,
    FlagVerificationRequest,
    RejectVerificationRequest,
    VerificationFindingCreateRequest,
    VerificationFindingResolveRequest,
    VerificationFindingResponse,
    VerificationPackageResponse,
    VerificationQueueItemResponse,
    VerificationRecordResponse,
)

router = APIRouter(prefix="/verification", tags=["Verification Engine"])


# ------------------------------------------------------------------------------
# 1. Verification Queue
# ------------------------------------------------------------------------------


@router.get(
    "/queue",
    response_model=List[VerificationQueueItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List recovery events pending verification",
)
async def get_verification_queue(
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
    material_type: Optional[str] = Query(None, description="Filter by plastic polymer type"),
    status_filter: Optional[RecoveryStatus] = Query(None, alias="status", description="Filter by recovery status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[VerificationQueueItemResponse]:
    """Retrieve items waiting in the human verification queue."""
    return await verification_service.get_verification_queue(
        requester=current_user,
        material_type=material_type,
        status=status_filter,
        skip=skip,
        limit=limit,
    )


# ------------------------------------------------------------------------------
# 2. Complete Verification Package
# ------------------------------------------------------------------------------


@router.get(
    "/package/{recovery_id}",
    response_model=VerificationPackageResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect complete verification dossier",
)
async def get_verification_package(
    recovery_id: uuid.UUID,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationPackageResponse:
    """Inspect full multi-party audit package (collection, logistics, delivery, evidence, weight, custody timeline)."""
    return await verification_service.get_verification_package(
        recovery_id=recovery_id, requester=current_user
    )


# ------------------------------------------------------------------------------
# 3. Action: APPROVE
# ------------------------------------------------------------------------------


@router.post(
    "/{recovery_id}/approve",
    response_model=VerificationRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve recovery event verification",
)
async def approve_recovery(
    recovery_id: uuid.UUID,
    data: ApproveVerificationRequest,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationRecordResponse:
    """Authoritative verifier grants verification approval.

    Performs strict server-side validation:
    - Verifier authorized
    - Recovery exists and not already verified
    - Material batch reached RECEIVED custody status
    - Required evidence files exist
    - Delivery confirmed received
    - No unresolved critical findings
    - Self-verification strictly forbidden
    """
    return await verification_service.approve_recovery(
        recovery_id=recovery_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 4. Action: REJECT
# ------------------------------------------------------------------------------


@router.post(
    "/{recovery_id}/reject",
    response_model=VerificationRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject recovery event verification",
)
async def reject_recovery(
    recovery_id: uuid.UUID,
    data: RejectVerificationRequest,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationRecordResponse:
    """Authoritative verifier rejects verification with mandatory rationale.

    Preserves all evidence, delivery records, and historical logs.
    """
    return await verification_service.reject_recovery(
        recovery_id=recovery_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 5. Action: FLAG / REQUEST_REVIEW
# ------------------------------------------------------------------------------


@router.post(
    "/{recovery_id}/flag",
    response_model=VerificationRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Flag recovery event for further review",
)
async def flag_recovery(
    recovery_id: uuid.UUID,
    data: FlagVerificationRequest,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationRecordResponse:
    """Flag discrepancies or request additional audit investigation."""
    return await verification_service.flag_recovery(
        recovery_id=recovery_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 6. Audit & Sentinel Findings
# ------------------------------------------------------------------------------


@router.post(
    "/{recovery_id}/findings",
    response_model=VerificationFindingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a verification finding or discrepancy",
)
async def add_finding(
    recovery_id: uuid.UUID,
    data: VerificationFindingCreateRequest,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationFindingResponse:
    """Log an audit discrepancy, anomaly, or Sentinel flag."""
    return await verification_service.add_finding(
        recovery_id=recovery_id, data=data, requester=current_user
    )


@router.post(
    "/findings/{finding_id}/resolve",
    response_model=VerificationFindingResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a verification finding",
)
async def resolve_finding(
    finding_id: uuid.UUID,
    data: VerificationFindingResolveRequest,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> VerificationFindingResponse:
    """Mark an audit discrepancy or Sentinel flag resolved with explanatory notes."""
    return await verification_service.resolve_finding(
        finding_id=finding_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 7. Verification History Records
# ------------------------------------------------------------------------------


@router.get(
    "/{recovery_id}/records",
    response_model=List[VerificationRecordResponse],
    status_code=status.HTTP_200_OK,
    summary="List verification determinations for recovery",
)
async def list_recovery_records(
    recovery_id: uuid.UUID,
    current_user: CurrentUserDep,
    verification_service: VerificationServiceDep,
) -> List[VerificationRecordResponse]:
    """List all historical verification determinations and audit records for a recovery event."""
    return await verification_service.list_recovery_records(
        recovery_id=recovery_id, requester=current_user
    )
