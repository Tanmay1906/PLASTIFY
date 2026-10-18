"""PLASTIFY Plastic Credit, Issuance, Transfer, and Retirement API Endpoints.

Handles:
- Credit batch formation from assessed eligible impacts
- Independent verifier/auditor batch approval (with self-approval prevention)
- Controlled issuance with idempotency and external registry timeout resiliency
- Serialized plastic credit listing and ownership tracking
- Credit transfers
- Permanent, tamper-evident credit retirement certificates
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    CreditServiceDep,
    CurrentUserDep,
    require_roles,
)
from app.models.credit import CreditBatchStatus, CreditStatus
from app.models.user import UserRole
from app.schemas.credit import (
    CreditBatchApproveRequest,
    CreditBatchCreateRequest,
    CreditBatchIssueRequest,
    CreditBatchResponse,
    CreditRetirementRequest,
    CreditRetirementResponse,
    CreditTransactionResponse,
    CreditTransferRequest,
    PlasticCreditResponse,
)

router = APIRouter(prefix="/credits", tags=["Credit Issuance & Retirement Engine"])


# ------------------------------------------------------------------------------
# 1. Credit Batches
# ------------------------------------------------------------------------------

@router.post(
    "/batches",
    response_model=CreditBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Draft Credit Batch",
    description="Assemble verified, eligible assessed impacts into a formal credit batch. Allocates source quantities under row lock.",
)
async def create_credit_batch(
    payload: CreditBatchCreateRequest,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(
        UserRole.CORPORATE,
        UserRole.COLLECTOR,
        UserRole.RECYCLER,
        UserRole.UPCYCLER,
        UserRole.SUPER_ADMIN,
    )),
) -> CreditBatchResponse:
    """Create a draft credit batch."""
    return await credit_service.create_credit_batch(payload, current_user)


@router.get(
    "/batches",
    response_model=List[CreditBatchResponse],
    summary="List Credit Batches",
    description="Retrieve credit batches with tenant isolation and optional status filter.",
)
async def list_credit_batches(
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    status: Optional[CreditBatchStatus] = Query(None, description="Filter by batch status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[CreditBatchResponse]:
    """List credit batches accessible to current user."""
    return await credit_service.list_batches(
        actor=current_user,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/batches/{batch_id}",
    response_model=CreditBatchResponse,
    summary="Get Credit Batch Details",
    description="Fetch a credit batch by UUID including source allocations, serialized credits, and issuance metadata.",
)
async def get_credit_batch(
    batch_id: uuid.UUID,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
) -> CreditBatchResponse:
    """Fetch credit batch by ID."""
    return await credit_service.get_batch_by_id(batch_id, current_user)


@router.post(
    "/batches/{batch_id}/approve",
    response_model=CreditBatchResponse,
    summary="Approve Credit Batch for Issuance",
    description="Authoritatively approve a credit batch. Enforces server-side self-approval and cross-organization separation.",
)
async def approve_credit_batch(
    batch_id: uuid.UUID,
    payload: CreditBatchApproveRequest,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN)),
) -> CreditBatchResponse:
    """Approve credit batch."""
    return await credit_service.approve_credit_batch(batch_id, payload, current_user)


@router.post(
    "/batches/{batch_id}/issue",
    response_model=CreditBatchResponse,
    summary="Controlled Credit Issuance",
    description="Execute controlled minting of serialized plastic credits. Enforces idempotency and registry connection resiliency.",
)
async def issue_credit_batch(
    batch_id: uuid.UUID,
    payload: CreditBatchIssueRequest,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.AUDITOR, UserRole.SUPER_ADMIN)),
) -> CreditBatchResponse:
    """Issue plastic credits from an approved batch."""
    return await credit_service.issue_credit_batch(batch_id, payload, current_user)


# ------------------------------------------------------------------------------
# 2. Plastic Credits & Ownership
# ------------------------------------------------------------------------------

@router.get(
    "",
    response_model=List[PlasticCreditResponse],
    summary="List Owned Plastic Credits",
    description="Retrieve serialized plastic credits owned by the user's organization.",
)
async def list_plastic_credits(
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    status: Optional[CreditStatus] = Query(None, description="Filter by credit status (ACTIVE, RETIRED, etc.)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[PlasticCreditResponse]:
    """List serialized credits."""
    return await credit_service.list_credits(
        actor=current_user,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/transfer",
    response_model=CreditTransactionResponse,
    summary="Transfer Plastic Credits",
    description="Transfer ownership of active plastic credits to another participating organization.",
)
async def transfer_credits(
    payload: CreditTransferRequest,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
) -> CreditTransactionResponse:
    """Transfer credits to another organization."""
    return await credit_service.transfer_credits(payload, current_user)


# ------------------------------------------------------------------------------
# 3. Credit Retirement
# ------------------------------------------------------------------------------

@router.post(
    "/retire",
    response_model=CreditRetirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retire Plastic Credits",
    description="Permanently retire plastic credits on behalf of a beneficiary. Terminally locks credits and generates a cryptographic certificate.",
)
async def retire_credits(
    payload: CreditRetirementRequest,
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
) -> CreditRetirementResponse:
    """Permanently retire credits."""
    return await credit_service.retire_credits(payload, current_user)


@router.get(
    "/retirements",
    response_model=List[CreditRetirementResponse],
    summary="List Credit Retirements",
    description="Retrieve permanent retirement certificate records.",
)
async def list_retirements(
    credit_service: CreditServiceDep,
    current_user: CurrentUserDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[CreditRetirementResponse]:
    """List retirement certificates."""
    return await credit_service.list_retirements(
        actor=current_user,
        skip=skip,
        limit=limit,
    )
