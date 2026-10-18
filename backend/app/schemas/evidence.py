"""PLASTIFY Evidence Management Pydantic Schemas."""

from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.evidence import EvidenceType


class EvidenceResponse(BaseModel):
    """Metadata response representing an auditable digital evidence record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recovery_id: uuid.UUID
    uploader_id: uuid.UUID
    uploader_name: Optional[str] = None
    type: EvidenceType
    storage_key: str
    original_filename: str
    mime_type: str
    size: int = Field(..., description="File size in bytes")
    sha256_hash: str = Field(..., description="Cryptographic SHA-256 checksum in hexadecimal")
    scan_status: str
    notes: Optional[str] = None
    created_at: datetime
    download_url: Optional[str] = Field(
        default=None, description="Short-lived secure presigned URL for downloading the file"
    )


class EvidenceSignedUrlResponse(BaseModel):
    """Presigned signed URL response for secure file retrieval."""

    evidence_id: uuid.UUID
    download_url: str
    expires_in_seconds: int
    sha256_hash: str
    mime_type: str
    original_filename: str
