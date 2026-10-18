"""PLASTIFY Evidence Management Domain Service.

Coordinates secure file uploads to S3/MinIO, malware scanning, cryptographic hashing,
metadata persistence in PostgreSQL, audit logging, and presigned signed URL retrieval.
"""

from datetime import datetime, timezone
import hashlib
import os
import re
from typing import List, Optional, Set
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.core.malware import BaseMalwareScanner
from app.core.storage import IStorageService
from app.models.evidence import Evidence, EvidenceType
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.evidence import EvidenceRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.repositories.recovery import RecoveryRepository
from app.schemas.evidence import EvidenceResponse, EvidenceSignedUrlResponse
from app.services.base import BaseService

DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".sh", ".bash",
    ".ps1", ".vbs", ".js", ".mjs", ".jar", ".py", ".pyc", ".php",
    ".phtml", ".asp", ".aspx", ".cgi", ".pl", ".htm", ".html",
    ".xhtml", ".svg", ".xml", ".scr", ".msi", ".bin", ".com",
}

ALLOWED_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".pdf"
}

ALLOWED_MIME_TYPES: Set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/tiff",
    "application/pdf",
}


class EvidenceService(BaseService):
    """Core domain service for collection proof and verification evidence."""

    def __init__(
        self,
        settings: Settings,
        evidence_repo: EvidenceRepository,
        recovery_repo: RecoveryRepository,
        program_repo: ProgramRepository,
        program_partner_repo: ProgramPartnerRepository,
        audit_repo: AuditRepository,
        storage_service: IStorageService,
        malware_scanner: BaseMalwareScanner,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.evidence_repo = evidence_repo
        self.recovery_repo = recovery_repo
        self.program_repo = program_repo
        self.program_partner_repo = program_partner_repo
        self.audit_repo = audit_repo
        self.storage_service = storage_service
        self.malware_scanner = malware_scanner

    async def upload_evidence(
        self,
        recovery_id: uuid.UUID,
        uploader: User,
        evidence_type: EvidenceType,
        file_content: bytes,
        filename: str,
        mime_type: str,
        notes: Optional[str] = None,
    ) -> EvidenceResponse:
        """Execute the 11-step secure evidence ingestion workflow."""
        # Step 1: Authenticate uploader (already verified via CurrentUserDep)
        if not uploader.is_active:
            raise ForbiddenException("Inactive user accounts cannot upload evidence.")

        # Step 2: Authorize access to the Recovery Event
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' does not exist.")

        await self._assert_recovery_access(recovery, uploader)

        if recovery.status in [RecoveryStatus.VERIFIED, RecoveryStatus.REJECTED, RecoveryStatus.CANCELLED]:
            raise BadRequestException(
                f"Cannot upload evidence: Recovery event is in terminal/locked status '{recovery.status.value}'."
            )

        # Step 3: Validate file size
        file_size = len(file_content)
        if file_size == 0:
            raise BadRequestException("Uploaded evidence file is empty (0 bytes).")

        max_size = self.settings.MAX_EVIDENCE_FILE_SIZE_BYTES
        if file_size > max_size:
            raise BadRequestException(
                f"File size ({file_size} bytes) exceeds maximum allowable limit of {max_size} bytes."
            )

        # Step 4 & 5: Validate MIME type, extension, and reject dangerous file types
        clean_filename = os.path.basename(filename.strip())
        _, raw_ext = os.path.splitext(clean_filename)
        ext = raw_ext.lower()

        if ext in DANGEROUS_EXTENSIONS:
            raise BadRequestException(
                f"File rejected: '{ext}' is a prohibited high-risk executable or script extension."
            )

        if ext not in ALLOWED_EXTENSIONS:
            raise BadRequestException(
                f"File extension '{ext}' is not permitted. Allowed: {sorted(list(ALLOWED_EXTENSIONS))}"
            )

        clean_mime = mime_type.strip().lower()
        if clean_mime not in ALLOWED_MIME_TYPES:
            raise BadRequestException(
                f"MIME type '{clean_mime}' is not permitted. Allowed: {sorted(list(ALLOWED_MIME_TYPES))}"
            )

        # Extra Step: Malware scan abstraction
        scan_result = await self.malware_scanner.scan(file_content, clean_filename)
        if not scan_result.is_clean:
            threat = scan_result.threat_name or "Malicious payload detected"
            self.logger.warning(
                f"Malware scan failed for upload by {uploader.email}: {threat}"
            )
            raise BadRequestException(f"File security verification failed: {threat}")

        # Step 6: Generate random storage key
        safe_base = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean_filename)
        storage_key = f"evidence/{recovery.id}/{uuid.uuid4().hex}_{safe_base}"

        # Step 7: Upload to object storage (MinIO / S3)
        self.storage_service.upload_file(
            file_content=file_content,
            storage_key=storage_key,
            content_type=clean_mime,
        )

        # Step 8: Calculate SHA-256 cryptographic hash
        sha256_hash = hashlib.sha256(file_content).hexdigest()

        # Step 9 & 10: Store metadata in PostgreSQL and associate with Recovery Event
        evidence = Evidence(
            recovery_id=recovery.id,
            uploader_id=uploader.id,
            type=evidence_type,
            storage_key=storage_key,
            original_filename=clean_filename,
            mime_type=clean_mime,
            size=file_size,
            sha256_hash=sha256_hash,
            scan_status="CLEAN",
            notes=notes.strip() if notes else None,
        )
        created_evidence = await self.evidence_repo.create(evidence)

        # Step 11: Create audit event
        await self.audit_repo.record(
            action="EVIDENCE_UPLOADED",
            resource=f"evidence:{created_evidence.id}",
            actor_id=uploader.id,
            actor_email=uploader.email,
            actor_role=uploader.role.value,
            metadata={
                "recovery_id": str(recovery.id),
                "evidence_id": str(created_evidence.id),
                "type": evidence_type.value,
                "size_bytes": file_size,
                "sha256": sha256_hash,
                "storage_key": storage_key,
            },
        )

        self.logger.info(
            f"Evidence '{created_evidence.id}' uploaded for recovery {recovery.recovery_id} by {uploader.email} (SHA256: {sha256_hash[:8]}...)"
        )

        return self._build_evidence_response(created_evidence)

    async def get_evidence(
        self, evidence_id: uuid.UUID, requester: User
    ) -> EvidenceResponse:
        """Retrieve evidence metadata with short-lived presigned download URL."""
        evidence = await self.evidence_repo.get_with_relations(evidence_id)
        if not evidence:
            raise NotFoundException("Evidence record not found.")

        recovery = await self.recovery_repo.get_by_id(evidence.recovery_id)
        if not recovery:
            raise NotFoundException("Associated recovery event not found.")

        await self._assert_recovery_access(recovery, requester)
        return self._build_evidence_response(evidence)

    async def get_signed_url(
        self, evidence_id: uuid.UUID, requester: User, expires_in: Optional[int] = None
    ) -> EvidenceSignedUrlResponse:
        """Generate a fresh short-lived signed URL for secure file retrieval."""
        evidence = await self.evidence_repo.get_by_id(evidence_id)
        if not evidence:
            raise NotFoundException("Evidence record not found.")

        recovery = await self.recovery_repo.get_by_id(evidence.recovery_id)
        if not recovery:
            raise NotFoundException("Associated recovery event not found.")

        await self._assert_recovery_access(recovery, requester)

        ttl = expires_in or self.settings.S3_SIGNED_URL_EXPIRE_SECONDS
        download_url = self.storage_service.generate_presigned_url(
            evidence.storage_key, expires_in=ttl
        )

        return EvidenceSignedUrlResponse(
            evidence_id=evidence.id,
            download_url=download_url,
            expires_in_seconds=ttl,
            sha256_hash=evidence.sha256_hash,
            mime_type=evidence.mime_type,
            original_filename=evidence.original_filename,
        )

    async def list_recovery_evidence(
        self, recovery_id: uuid.UUID, requester: User, skip: int = 0, limit: int = 50
    ) -> List[EvidenceResponse]:
        """List all digital proof files associated with a recovery event."""
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException("Recovery event not found.")

        await self._assert_recovery_access(recovery, requester)

        records = await self.evidence_repo.list_by_recovery(recovery.id, skip=skip, limit=limit)
        return [self._build_evidence_response(e) for e in records]

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------

    async def _assert_recovery_access(
        self, recovery: RecoveryEvent, user: User
    ) -> None:
        """Enforce strict authorization and tenant isolation for recovery evidence."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        # 1. Collector who created the event
        if recovery.collector_id == user.id:
            return

        # 2. Member of creating collector organization
        if user.organization_id and user.organization_id == recovery.collector_organization_id:
            return

        # 3. Corporate brand owner of the program
        program = await self.program_repo.get_by_id(recovery.program_id)
        if program and user.organization_id and user.organization_id == program.organization_id:
            return

        # 4. Assigned operational partner organization (e.g., Logistics, Verifier, Recycler)
        if user.organization_id and await self.program_partner_repo.is_partner_assigned(
            recovery.program_id, user.organization_id
        ):
            return

        raise ForbiddenException(
            "Access denied: You do not have permission to access evidence for this recovery event.",
            error_code="RESOURCE_FORBIDDEN",
        )

    def _build_evidence_response(self, evidence: Evidence) -> EvidenceResponse:
        """Construct EvidenceResponse including short-lived presigned download URL."""
        download_url = self.storage_service.generate_presigned_url(
            evidence.storage_key, expires_in=self.settings.S3_SIGNED_URL_EXPIRE_SECONDS
        )
        uploader_name = (
            evidence.uploader.full_name if evidence.uploader else None
        )

        return EvidenceResponse(
            id=evidence.id,
            recovery_id=evidence.recovery_id,
            uploader_id=evidence.uploader_id,
            uploader_name=uploader_name,
            type=evidence.type,
            storage_key=evidence.storage_key,
            original_filename=evidence.original_filename,
            mime_type=evidence.mime_type,
            size=evidence.size,
            sha256_hash=evidence.sha256_hash,
            scan_status=evidence.scan_status,
            notes=evidence.notes,
            created_at=evidence.created_at,
            download_url=download_url,
        )
