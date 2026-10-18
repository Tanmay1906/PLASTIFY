"""PLASTIFY Upcycling Manufacturing API Endpoints.

Handles circular material allocation, upcycling batch lifecycle,
quality control specifications, and finished product registration.
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.dependencies import (
    CurrentUserDep,
    UpcyclingServiceDep,
    require_roles,
)
from app.models.circular import UpcyclingBatchStatus
from app.models.user import UserRole
from app.schemas.circular import (
    AvailableRecycledMaterialResponse,
    ProductCreateRequest,
    ProductResponse,
    UpcyclingBatchCompleteRequest,
    UpcyclingBatchCreateRequest,
    UpcyclingBatchEvidenceResponse,
    UpcyclingBatchResponse,
    UpcyclingQualityUpdateRequest,
)

router = APIRouter(prefix="/upcycling", tags=["Upcycling Engine"])


@router.get(
    "/available-materials",
    response_model=List[AvailableRecycledMaterialResponse],
    summary="List Available Recycled Materials",
    description="Query completed recycled material batches that have unallocated secondary raw material output ready for upcycling.",
)
async def list_available_materials(
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    material_type: Optional[str] = Query(None, description="Optional plastic type filter (e.g. PET, HDPE)"),
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.CORPORATE, UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN)),
) -> List[AvailableRecycledMaterialResponse]:
    """List available secondary raw materials."""
    return await upcycling_service.list_available_materials(current_user, material_type=material_type)


@router.post(
    "/batches",
    response_model=UpcyclingBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Upcycling Batch",
    description="Initiate a new upcycling manufacturing batch by allocating material from completed MaterialBatches.",
)
async def create_upcycling_batch(
    payload: UpcyclingBatchCreateRequest,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.SUPER_ADMIN)),
) -> UpcyclingBatchResponse:
    """Create an upcycling batch."""
    return await upcycling_service.create_upcycling_batch(payload, current_user)


@router.get(
    "/batches",
    response_model=List[UpcyclingBatchResponse],
    summary="List Upcycling Batches",
    description="List upcycling production batches scoped to the authenticated upcycler's organization.",
)
async def list_upcycling_batches(
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    batch_status: Optional[UpcyclingBatchStatus] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.AUDITOR, UserRole.VERIFIER, UserRole.SUPER_ADMIN)),
) -> List[UpcyclingBatchResponse]:
    """List upcycling batches."""
    return await upcycling_service.list_upcycling_batches(
        current_user, status=batch_status, skip=skip, limit=limit
    )


@router.get(
    "/batches/{batch_id}",
    response_model=UpcyclingBatchResponse,
    summary="Get Upcycling Batch Details",
    description="Retrieve details for an upcycling batch including material allocations, quality rating, and registered products.",
)
async def get_upcycling_batch(
    batch_id: uuid.UUID,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.AUDITOR, UserRole.VERIFIER, UserRole.CORPORATE, UserRole.SUPER_ADMIN)),
) -> UpcyclingBatchResponse:
    """Get upcycling batch by primary key."""
    return await upcycling_service.get_upcycling_batch(batch_id, current_user)


@router.patch(
    "/batches/{batch_id}/quality",
    response_model=UpcyclingBatchResponse,
    summary="Record Quality Verification",
    description="Submit QA inspection results, grading, and certification notes for an upcycling batch.",
)
async def update_quality_verification(
    batch_id: uuid.UUID,
    payload: UpcyclingQualityUpdateRequest,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN)),
) -> UpcyclingBatchResponse:
    """Record QA inspection specifications."""
    return await upcycling_service.update_quality(batch_id, payload, current_user)


@router.post(
    "/batches/{batch_id}/evidence",
    response_model=UpcyclingBatchEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Production Evidence",
    description="Upload photographic, QA specification, or manufacturing proof files for an upcycling batch.",
)
async def upload_production_evidence(
    batch_id: uuid.UUID,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    file: UploadFile = File(...),
    evidence_type: str = Form("PRODUCTION_PROOF"),
    notes: Optional[str] = Form(None),
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.SUPER_ADMIN)),
) -> UpcyclingBatchEvidenceResponse:
    """Attach manufacturing documentation to an upcycling batch."""
    file_bytes = await file.read()
    filename = file.filename or "evidence.jpg"
    content_type = file.content_type or "application/octet-stream"
    return await upcycling_service.upload_evidence(
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
    response_model=UpcyclingBatchResponse,
    summary="Complete Upcycling Batch",
    description="Finalize upcycling production batch and record final finished product quantity.",
)
async def complete_upcycling_batch(
    batch_id: uuid.UUID,
    payload: UpcyclingBatchCompleteRequest,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.SUPER_ADMIN)),
) -> UpcyclingBatchResponse:
    """Finalize upcycling batch."""
    return await upcycling_service.complete_upcycling_batch(batch_id, payload, current_user)


@router.post(
    "/batches/{batch_id}/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Circular Product & Issue Product Passport",
    description="Register a commercial circular product fabricated from an upcycling batch and generate its QR-ready Digital Product Passport.",
)
async def register_circular_product(
    batch_id: uuid.UUID,
    payload: ProductCreateRequest,
    upcycling_service: UpcyclingServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.UPCYCLER, UserRole.SUPER_ADMIN)),
) -> ProductResponse:
    """Register circular product and issue DPP."""
    return await upcycling_service.register_product(batch_id, payload, current_user)
