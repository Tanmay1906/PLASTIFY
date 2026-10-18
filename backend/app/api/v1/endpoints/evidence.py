"""PLASTIFY Evidence Management API Endpoints.

Implements secure digital evidence file uploads (multipart/form-data),
cryptographic hash verification, metadata association with Recovery Events,
and short-lived presigned signed URL generation for secure retrieval.
"""

from typing import List, Optional
import uuid
from fastapi import (
    APIRouter,
    File,
    Form,
    Query,
    UploadFile,
    status,
)

from app.core.dependencies import (
    CurrentUserDep,
    EvidenceServiceDep,
)
from app.models.evidence import EvidenceType
from app.schemas.evidence import (
    EvidenceResponse,
    EvidenceSignedUrlResponse,
)

router = APIRouter(tags=["Evidence & Secure Object Storage"])


@router.post(
    "/recoveries/{recovery_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Recovery Evidence File",
    description=(
        "Upload photographic proof, scale receipts, or delivery documentation to S3/MinIO. "
        "Calculates cryptographic SHA-256 hash, runs malware checks, and records metadata."
    ),
)
async def upload_recovery_evidence(
    recovery_id: uuid.UUID,
    file: UploadFile = File(..., description="Binary proof file (image/pdf)"),
    evidence_type: EvidenceType = Form(
        default=EvidenceType.COLLECTION_PHOTO, description="Classification of evidence"
    ),
    notes: Optional[str] = Form(
        default=None, description="Operational notes accompanying this evidence"
    ),
    current_user: CurrentUserDep = None,
    service: EvidenceServiceDep = None,
) -> EvidenceResponse:
    """Upload digital proof file for a recovery event."""
    file_bytes = await file.read()
    filename = file.filename or "evidence.bin"
    content_type = file.content_type or "application/octet-stream"

    return await service.upload_evidence(
        recovery_id=recovery_id,
        uploader=current_user,
        evidence_type=evidence_type,
        file_content=file_bytes,
        filename=filename,
        mime_type=content_type,
        notes=notes,
    )


@router.get(
    "/recoveries/{recovery_id}/evidence",
    response_model=List[EvidenceResponse],
    summary="List Evidence for Recovery Event",
    description="Retrieve all digital evidence records attached to a recovery event with signed URLs.",
)
async def list_recovery_evidence(
    recovery_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: EvidenceServiceDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[EvidenceResponse]:
    """List all evidence attached to a recovery event."""
    return await service.list_recovery_evidence(
        recovery_id=recovery_id, requester=current_user, skip=skip, limit=limit
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceResponse,
    summary="Get Evidence Metadata & Download URL",
    description="Retrieve metadata and short-lived signed URL for an individual evidence item.",
)
async def get_evidence(
    evidence_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: EvidenceServiceDep,
) -> EvidenceResponse:
    """Get single evidence record with presigned URL."""
    return await service.get_evidence(evidence_id=evidence_id, requester=current_user)


@router.get(
    "/evidence/{evidence_id}/url",
    response_model=EvidenceSignedUrlResponse,
    summary="Generate Fresh Presigned Download URL",
    description="Generate a fresh, short-lived presigned URL for downloading an evidence file.",
)
async def get_evidence_signed_url(
    evidence_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: EvidenceServiceDep,
    expires_in: Optional[int] = Query(
        default=None, ge=60, le=86400, description="URL validity in seconds (60-86400)"
    ),
) -> EvidenceSignedUrlResponse:
    """Generate fresh signed URL for secure file retrieval."""
    return await service.get_signed_url(
        evidence_id=evidence_id, requester=current_user, expires_in=expires_in
    )
