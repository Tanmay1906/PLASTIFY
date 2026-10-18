"""PLASTIFY Recycling Engine API Endpoints.

Handles verified raw material intake, industrial recycling batch lifecycle,
mass conservation enforcement, and digital material passports.
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.dependencies import (
    CurrentUserDep,
    RecyclingServiceDep,
    require_roles,
)
from app.models.circular import MaterialBatchStatus
from app.models.user import UserRole
from app.schemas.circular import (
    IncomingMaterialResponse,
    MaterialBatchCreateRequest,
    MaterialBatchEvidenceResponse,
    MaterialBatchProcessingUpdateRequest,
    MaterialBatchResponse,
    MaterialPassportResponse,
)

router = APIRouter(prefix="/recycling", tags=["Recycling Engine"])


@router.get(
    "/incoming-materials",
    response_model=List[IncomingMaterialResponse],
    summary="List Incoming Verified Materials",
    description="Retrieve verified recovery events eligible to be drawn into an industrial recycling processing batch.",
)
async def list_incoming_materials(
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.SUPER_ADMIN)),
) -> List[IncomingMaterialResponse]:
    """List verified materials delivered or allocated to this recycler."""
    return await recycling_service.list_incoming_materials(current_user)


@router.post(
    "/batches",
    response_model=MaterialBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Material Processing Batch",
    description="Initiate a new recycling batch by drawing verified input recovery events.",
)
async def create_material_batch(
    payload: MaterialBatchCreateRequest,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.SUPER_ADMIN)),
) -> MaterialBatchResponse:
    """Create a new recycling batch."""
    return await recycling_service.create_material_batch(payload, current_user)


@router.get(
    "/batches",
    response_model=List[MaterialBatchResponse],
    summary="List Material Batches",
    description="List recycling batches scoped to the authenticated recycler's organization.",
)
async def list_material_batches(
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    batch_status: Optional[MaterialBatchStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.AUDITOR, UserRole.VERIFIER, UserRole.SUPER_ADMIN)),
) -> List[MaterialBatchResponse]:
    """List material batches."""
    return await recycling_service.list_material_batches(
        current_user, status=batch_status, skip=skip, limit=limit
    )


@router.get(
    "/batches/{batch_id}",
    response_model=MaterialBatchResponse,
    summary="Get Material Batch Details",
    description="Retrieve full details for an industrial recycling batch including source recoveries and evidence.",
)
async def get_material_batch(
    batch_id: uuid.UUID,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.UPCYCLER, UserRole.AUDITOR, UserRole.VERIFIER, UserRole.SUPER_ADMIN)),
) -> MaterialBatchResponse:
    """Retrieve material batch by primary key."""
    return await recycling_service.get_material_batch(batch_id, current_user)


@router.patch(
    "/batches/{batch_id}/processing",
    response_model=MaterialBatchResponse,
    summary="Update Processing Yields",
    description="Record recycled output and residual waste with strict mass conservation validation (output + residual <= input).",
)
async def update_processing_yields(
    batch_id: uuid.UUID,
    payload: MaterialBatchProcessingUpdateRequest,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.SUPER_ADMIN)),
) -> MaterialBatchResponse:
    """Record recycled output and residual material."""
    return await recycling_service.update_processing(batch_id, payload, current_user)


@router.post(
    "/batches/{batch_id}/evidence",
    response_model=MaterialBatchEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Processing Evidence",
    description="Upload photographic, scale, or lab documentation for a material batch.",
)
async def upload_processing_evidence(
    batch_id: uuid.UUID,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    file: UploadFile = File(...),
    evidence_type: str = Form("PROCESSING_PROOF"),
    notes: Optional[str] = Form(None),
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.SUPER_ADMIN)),
) -> MaterialBatchEvidenceResponse:
    """Attach digital processing proof to a recycling batch."""
    file_bytes = await file.read()
    filename = file.filename or "evidence.jpg"
    content_type = file.content_type or "application/octet-stream"
    return await recycling_service.upload_evidence(
        batch_id=batch_id,
        file_bytes=file_bytes,
        filename=filename,
        mime_type=content_type,
        evidence_type=evidence_type,
        notes=notes,
        requester=current_user,
    )


@router.post(
    "/batches/{batch_id}/complete",
    response_model=MaterialBatchResponse,
    summary="Complete Processing & Issue Material Passport",
    description="Finalize industrial recycling processing, lock mass conservation, and generate the Digital Material Passport.",
)
async def complete_processing_batch(
    batch_id: uuid.UUID,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.SUPER_ADMIN)),
) -> MaterialBatchResponse:
    """Complete recycling batch and issue material passport."""
    return await recycling_service.complete_processing(batch_id, current_user)


@router.get(
    "/batches/{batch_id}/passport",
    response_model=MaterialPassportResponse,
    summary="Get Material Passport",
    description="Retrieve the Digital Material Passport credentials for a completed recycling batch.",
)
async def get_material_passport(
    batch_id: uuid.UUID,
    recycling_service: RecyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.UPCYCLER, UserRole.AUDITOR, UserRole.VERIFIER, UserRole.CORPORATE, UserRole.SUPER_ADMIN)),
) -> MaterialPassportResponse:
    """Retrieve material passport."""
    return await recycling_service.get_material_passport(str(batch_id), current_user)
