"""PLASTIFY Industrial Recycling Domain Service.

Enforces mass balance conservation:
    recycled_output + residual <= input_weight
Prevents impossible mass accounting, tracks verified recovery provenance, and issues Material Passports.
"""

from datetime import datetime, timezone
import hashlib
import logging
import re
from typing import List, Optional
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.core.storage import IStorageService
from app.models.circular import (
    MaterialBatch,
    MaterialBatchEvidence,
    MaterialBatchItem,
    MaterialBatchStatus,
    MaterialPassport,
)
from app.models.custody import CustodyState
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.circular import CircularRepository
from app.repositories.custody import ChainOfCustodyRepository
from app.repositories.recovery import RecoveryRepository
from app.schemas.circular import (
    IncomingMaterialResponse,
    MaterialBatchCreateRequest,
    MaterialBatchEvidenceResponse,
    MaterialBatchItemResponse,
    MaterialBatchProcessingUpdateRequest,
    MaterialBatchResponse,
    MaterialPassportResponse,
)
from app.schemas.custody import CustodyTransitionRequest
from app.services.base import BaseService
from app.services.custody import ChainOfCustodyService

logger = logging.getLogger("plastify.services.recycling")


class RecyclingService(BaseService):
    """Domain service orchestrating plastic recycling operations, mass conservation, and material passports."""

    def __init__(
        self,
        circular_repo: CircularRepository,
        recovery_repo: RecoveryRepository,
        custody_service: ChainOfCustodyService,
        custody_repo: ChainOfCustodyRepository,
        audit_repo: AuditRepository,
        storage_service: IStorageService,
        settings: Settings,
    ) -> None:
        super().__init__()
        self.circular_repo = circular_repo
        self.recovery_repo = recovery_repo
        self.custody_service = custody_service
        self.custody_repo = custody_repo
        self.audit_repo = audit_repo
        self.storage_service = storage_service
        self.settings = settings

    # --------------------------------------------------------------------------
    # 1. Incoming Verified Material
    # --------------------------------------------------------------------------

    async def list_incoming_materials(
        self, requester: User, recycler_org_id: Optional[uuid.UUID] = None
    ) -> List[IncomingMaterialResponse]:
        """Fetch verified recovery materials ready for intake and processing."""
        target_org_id = recycler_org_id or requester.organization_id
        if requester.role != UserRole.SUPER_ADMIN and not target_org_id:
            raise ForbiddenException("User must belong to a recycler organization.")

        raw_materials = await self.circular_repo.list_incoming_verified_materials(
            recycler_org_id=target_org_id if requester.role != UserRole.SUPER_ADMIN else None
        )

        incoming: List[IncomingMaterialResponse] = []
        for rec, delivery, already_alloc in raw_materials:
            verified_weight = rec.weight_kg
            if delivery and delivery.received_weight_kg:
                verified_weight = delivery.received_weight_kg

            available = max(0.0, round(verified_weight - already_alloc, 3))
            incoming.append(
                IncomingMaterialResponse(
                    recovery_id=rec.id,
                    recovery_human_id=rec.recovery_id,
                    program_id=rec.program_id,
                    program_name=rec.program.name if rec.program else None,
                    material_type=rec.material_type,
                    collected_weight_kg=rec.weight_kg,
                    delivered_weight_kg=delivery.delivered_weight_kg if delivery else None,
                    verified_weight_kg=verified_weight,
                    already_allocated_weight_kg=already_alloc,
                    available_weight_kg=available,
                    collection_location=rec.collection_location,
                    collected_at=rec.collected_at,
                    delivery_code=delivery.delivery_code if delivery else None,
                    destination_organization_id=delivery.recycler_organization_id if delivery else None,
                )
            )

        return incoming

    # --------------------------------------------------------------------------
    # 2. Material Processing Batch Creation
    # --------------------------------------------------------------------------

    async def create_material_batch(
        self, data: MaterialBatchCreateRequest, requester: User
    ) -> MaterialBatchResponse:
        """Create a new industrial recycling batch drawing verified raw recovery events."""
        if requester.role not in [UserRole.RECYCLER, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only certified Recyclers or Super Admins can create material batches.")

        if not requester.organization_id and requester.role != UserRole.SUPER_ADMIN:
            raise ForbiddenException("Recycler must belong to an active organization.")

        clean_type = data.material_type.strip().upper()
        target_org_id = requester.organization_id

        # Validate input recovery events and check available weights
        total_input_weight = 0.0
        batch_items: List[MaterialBatchItem] = []

        for item_in in data.source_items:
            rec = await self.recovery_repo.get_by_id(item_in.recovery_id)
            if not rec:
                raise NotFoundException(f"Recovery event '{item_in.recovery_id}' was not found.")

            if rec.status != RecoveryStatus.VERIFIED and rec.custody_status != CustodyState.VERIFIED.value:
                raise BadRequestException(
                    f"Recovery event '{rec.recovery_id}' has not been officially VERIFIED. "
                    "Unverified materials cannot be admitted into circular processing."
                )

            if rec.material_type.strip().upper() != clean_type:
                raise BadRequestException(
                    f"Material mismatch: Recovery '{rec.recovery_id}' is of type '{rec.material_type}', "
                    f"which does not match batch material type '{clean_type}'."
                )

            # Check already committed weight
            already_alloc = await self.circular_repo.get_recovery_allocated_weight(rec.id)
            available = max(0.0, round(rec.weight_kg - already_alloc, 3))

            if item_in.allocated_weight_kg > available + 0.001:
                raise BadRequestException(
                    f"Over-allocation error on recovery '{rec.recovery_id}': Requested {item_in.allocated_weight_kg} kg, "
                    f"but only {available} kg verified weight remains unallocated."
                )

            total_input_weight += item_in.allocated_weight_kg
            batch_items.append(
                MaterialBatchItem(
                    recovery_event_id=rec.id,
                    allocated_weight_kg=round(item_in.allocated_weight_kg, 3),
                )
            )

        total_input_weight = round(total_input_weight, 3)
        if total_input_weight <= 0.0:
            raise BadRequestException("Total input weight must be greater than zero.")

        # Generate unique human-readable batch identifier (e.g. MB-2026-F981A4B2)
        year = datetime.now(timezone.utc).year
        batch_code = f"MB-{year}-{uuid.uuid4().hex[:8].upper()}"

        batch = MaterialBatch(
            batch_id=batch_code,
            recycler_organization_id=target_org_id,
            processor_id=requester.id,
            material_type=clean_type,
            input_weight_kg=total_input_weight,
            recycled_output_kg=0.0,
            residual_kg=0.0,
            processing_date=datetime.now(timezone.utc),
            status=MaterialBatchStatus.CREATED,
            verification_reference=data.verification_reference.strip() if data.verification_reference else None,
            notes=data.notes.strip() if data.notes else None,
            metadata_json=data.metadata or {},
        )
        batch.items.extend(batch_items)

        created_batch = await self.circular_repo.create(batch)

        await self.audit_repo.record(
            action="MATERIAL_BATCH_CREATED",
            resource=f"material_batch:{created_batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch_code,
                "material_type": clean_type,
                "input_weight_kg": total_input_weight,
                "source_items_count": len(batch_items),
            },
        )

        logger.info(
            f"Material Batch {batch_code} ({clean_type}, {total_input_weight}kg) created by {requester.email}"
        )

        refreshed = await self.circular_repo.get_material_batch_by_id(created_batch.id)
        return self._build_material_batch_response(refreshed or created_batch)

    # --------------------------------------------------------------------------
    # 3. Update Processing & Enforce Mass Conservation
    # --------------------------------------------------------------------------

    async def update_processing(
        self,
        batch_id: uuid.UUID,
        data: MaterialBatchProcessingUpdateRequest,
        requester: User,
    ) -> MaterialBatchResponse:
        """Record recycled output yield and residual waste with strict mass conservation validation."""
        batch = await self.circular_repo.get_material_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException(f"Material batch '{batch_id}' was not found.")

        self._assert_batch_ownership(batch, requester)

        if batch.status in [MaterialBatchStatus.COMPLETED, MaterialBatchStatus.CANCELLED]:
            raise BadRequestException(f"Cannot update processing yields on a '{batch.status.value}' batch.")

        # Business Invariant Enforcement:
        # recycled_output + residual <= input_weight
        out_kg = round(data.recycled_output_kg, 3)
        res_kg = round(data.residual_kg, 3)
        mass_sum = round(out_kg + res_kg, 3)

        if mass_sum > round(batch.input_weight_kg, 3) + 0.001:
            raise BadRequestException(
                f"Impossible mass accounting: Recycled output ({out_kg} kg) + residual ({res_kg} kg) = {mass_sum} kg, "
                f"which exceeds the input weight ({batch.input_weight_kg} kg). Physical mass conservation must be preserved."
            )

        batch.recycled_output_kg = out_kg
        batch.residual_kg = res_kg
        if data.notes:
            batch.notes = data.notes.strip()
        if data.verification_reference:
            batch.verification_reference = data.verification_reference.strip()
        if data.metadata:
            batch.metadata_json = {**(batch.metadata_json or {}), **data.metadata}

        if batch.status == MaterialBatchStatus.CREATED:
            batch.status = MaterialBatchStatus.IN_PROCESSING

        await self.circular_repo.session.flush()

        await self.audit_repo.record(
            action="MATERIAL_BATCH_YIELDS_RECORDED",
            resource=f"material_batch:{batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch.batch_id,
                "input_weight_kg": batch.input_weight_kg,
                "recycled_output_kg": out_kg,
                "residual_kg": res_kg,
                "yield_pct": batch.yield_percentage,
            },
        )

        logger.info(
            f"Material Batch {batch.batch_id} yields recorded: {out_kg}kg output, {res_kg}kg residual (Yield: {batch.yield_percentage}%)"
        )

        refreshed = await self.circular_repo.get_material_batch_by_id(batch.id)
        return self._build_material_batch_response(refreshed or batch)

    # --------------------------------------------------------------------------
    # 4. Upload Processing Evidence
    # --------------------------------------------------------------------------

    async def upload_evidence(
        self,
        batch_id: uuid.UUID,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        evidence_type: str,
        notes: Optional[str],
        requester: User,
    ) -> MaterialBatchEvidenceResponse:
        """Upload photographic, lab, or weighbridge documentation for a material batch."""
        batch = await self.circular_repo.get_material_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Material batch not found.")

        self._assert_batch_ownership(batch, requester)

        clean_filename = filename.strip()
        safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean_filename)
        storage_key = f"circular/material_batches/{batch.id}/{uuid.uuid4().hex}_{safe_name}"

        self.storage_service.upload_file(
            file_content=file_bytes,
            storage_key=storage_key,
            content_type=mime_type,
        )

        sha256 = hashlib.sha256(file_bytes).hexdigest()

        evidence = MaterialBatchEvidence(
            material_batch_id=batch.id,
            uploader_id=requester.id,
            evidence_type=evidence_type.strip().upper(),
            storage_key=storage_key,
            original_filename=clean_filename,
            mime_type=mime_type,
            file_size=len(file_bytes),
            sha256_hash=sha256,
            notes=notes.strip() if notes else None,
        )
        created_ev = await self.circular_repo.add_material_batch_evidence(evidence)

        logger.info(f"Evidence '{created_ev.id}' attached to material batch {batch.batch_id}")
        return MaterialBatchEvidenceResponse(
            id=created_ev.id,
            material_batch_id=batch.id,
            uploader_id=requester.id,
            uploader_name=requester.full_name,
            evidence_type=created_ev.evidence_type,
            original_filename=clean_filename,
            file_size=len(file_bytes),
            sha256_hash=sha256,
            notes=created_ev.notes,
            created_at=created_ev.created_at,
        )

    # --------------------------------------------------------------------------
    # 5. Complete Processing & Issue Material Passport
    # --------------------------------------------------------------------------

    async def complete_processing(
        self, batch_id: uuid.UUID, requester: User
    ) -> MaterialBatchResponse:
        """Finalize material batch, lock mass conservation, and generate Digital Material Passport."""
        batch = await self.circular_repo.get_material_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Material batch not found.")

        self._assert_batch_ownership(batch, requester)

        if batch.status == MaterialBatchStatus.COMPLETED:
            raise BadRequestException("Material batch is already COMPLETED.")

        # Mass conservation validation
        mass_sum = round(batch.recycled_output_kg + batch.residual_kg, 3)
        if mass_sum > round(batch.input_weight_kg, 3) + 0.001:
            raise BadRequestException(
                f"Cannot complete batch: Recycled output + residual ({mass_sum}kg) exceeds input weight ({batch.input_weight_kg}kg)."
            )

        if mass_sum <= 0.0:
            raise BadRequestException(
                "Cannot complete batch with zero output and zero residual. Record processing yields before completion."
            )

        batch.status = MaterialBatchStatus.COMPLETED

        # Generate Digital Material Passport
        year = datetime.now(timezone.utc).year
        passport_code = f"MP-{year}-{uuid.uuid4().hex[:8].upper()}"
        qr_id = f"QR-MP-{uuid.uuid4().hex[:12].upper()}"

        passport = MaterialPassport(
            passport_code=passport_code,
            material_batch_id=batch.id,
            qr_code_identifier=qr_id,
            issuer_organization_id=batch.recycler_organization_id,
            issued_at=datetime.now(timezone.utc),
            metadata_json={
                "batch_id": batch.batch_id,
                "material_type": batch.material_type,
                "input_weight_kg": batch.input_weight_kg,
                "recycled_output_kg": batch.recycled_output_kg,
                "residual_kg": batch.residual_kg,
                "yield_percentage": batch.yield_percentage,
                "verification_reference": batch.verification_reference,
            },
        )
        await self.circular_repo.create_material_passport(passport)
        batch.passport = passport

        # Transition Chain of Custody for each source recovery event to PROCESSED
        for item in batch.items:
            try:
                await self.custody_service.transition_custody(
                    item.recovery_event_id,
                    CustodyTransitionRequest(
                        new_state=CustodyState.PROCESSED,
                        notes=f"Recycled in Material Batch {batch.batch_id} ({passport_code})",
                        metadata={
                            "batch_id": batch.batch_id,
                            "passport_code": passport_code,
                            "allocated_weight_kg": item.allocated_weight_kg,
                        },
                    ),
                    requester,
                )
            except Exception as exc:
                logger.warning(f"Custody transition note for {item.recovery_event_id}: {exc}")

        await self.circular_repo.session.flush()

        await self.audit_repo.record(
            action="MATERIAL_BATCH_COMPLETED",
            resource=f"material_batch:{batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch.batch_id,
                "passport_code": passport_code,
                "output_kg": batch.recycled_output_kg,
                "residual_kg": batch.residual_kg,
            },
        )

        logger.info(f"Material Batch {batch.batch_id} COMPLETED. Issued Material Passport {passport_code}")

        refreshed = await self.circular_repo.get_material_batch_by_id(batch.id)
        return self._build_material_batch_response(refreshed or batch)

    # --------------------------------------------------------------------------
    # 6. Get Batch & Passport Details
    # --------------------------------------------------------------------------

    async def get_material_batch(
        self, batch_id: uuid.UUID, requester: User
    ) -> MaterialBatchResponse:
        """Retrieve material batch details with access enforcement."""
        batch = await self.circular_repo.get_material_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Material batch not found.")

        self._assert_can_view_batch(batch, requester)
        return self._build_material_batch_response(batch)

    async def list_material_batches(
        self,
        requester: User,
        status: Optional[MaterialBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[MaterialBatchResponse]:
        """List material batches accessible to requester."""
        target_org = requester.organization_id if requester.role != UserRole.SUPER_ADMIN else None
        batches = await self.circular_repo.list_material_batches(
            recycler_org_id=target_org,
            status=status,
            skip=skip,
            limit=limit,
        )
        return [self._build_material_batch_response(b) for b in batches]

    async def get_material_passport(
        self, code: str, requester: Optional[User] = None
    ) -> MaterialPassportResponse:
        """Retrieve Material Passport credentials by passport code or batch ID."""
        passport = await self.circular_repo.get_material_passport_by_code(code)
        if not passport:
            # Try fetching via material batch code
            batch = await self.circular_repo.get_material_batch_by_code(code)
            if batch and batch.passport:
                passport = batch.passport
            else:
                raise NotFoundException(f"Material passport for '{code}' was not found.")

        batch = passport.material_batch
        recovery_ids = [it.recovery.recovery_id for it in batch.items if it.recovery]

        return MaterialPassportResponse(
            passport_code=passport.passport_code,
            material_batch_id=batch.id,
            batch_human_id=batch.batch_id,
            material_type=batch.material_type,
            input_weight_kg=batch.input_weight_kg,
            recycled_output_kg=batch.recycled_output_kg,
            residual_kg=batch.residual_kg,
            yield_percentage=batch.yield_percentage,
            recycler_organization_name=batch.recycler_organization.name if batch.recycler_organization else "Certified Recycler",
            processing_date=batch.processing_date,
            qr_code_identifier=passport.qr_code_identifier,
            verification_reference=batch.verification_reference,
            source_recoveries_count=len(batch.items),
            source_recovery_ids=recovery_ids,
            mass_accounting={
                "input_weight_kg": batch.input_weight_kg,
                "recycled_output_kg": batch.recycled_output_kg,
                "residual_kg": batch.residual_kg,
                "yield_pct": batch.yield_percentage,
                "allocated_upcycling_kg": batch.allocated_upcycling_weight_kg,
                "available_upcycling_kg": batch.available_for_upcycling_kg,
            },
            issued_at=passport.issued_at,
        )

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------

    def _assert_batch_ownership(self, batch: MaterialBatch, user: User) -> None:
        if user.role == UserRole.SUPER_ADMIN:
            return
        if not user.organization_id or user.organization_id != batch.recycler_organization_id:
            raise ForbiddenException("Access denied: You do not have permission to manage this material batch.")

    def _assert_can_view_batch(self, batch: MaterialBatch, user: User) -> None:
        if user.role in [UserRole.SUPER_ADMIN, UserRole.AUDITOR, UserRole.VERIFIER]:
            return
        if user.organization_id and user.organization_id == batch.recycler_organization_id:
            return
        if user.role == UserRole.UPCYCLER:
            # Upcyclers can view completed batches
            if batch.status == MaterialBatchStatus.COMPLETED:
                return
        raise ForbiddenException("Access denied: You do not have permission to inspect this material batch.")

    def _build_material_batch_response(self, batch: MaterialBatch) -> MaterialBatchResponse:
        items_resp = [
            MaterialBatchItemResponse(
                id=it.id,
                recovery_id=it.recovery_event_id,
                recovery_human_id=it.recovery.recovery_id if it.recovery else None,
                allocated_weight_kg=it.allocated_weight_kg,
                verified_weight_kg=it.recovery.weight_kg if it.recovery else it.allocated_weight_kg,
                material_type=it.recovery.material_type if it.recovery else batch.material_type,
                collected_at=it.recovery.collected_at if it.recovery else None,
                collection_location=it.recovery.collection_location if it.recovery else None,
            )
            for it in (batch.items or [])
        ]

        ev_resp = [
            MaterialBatchEvidenceResponse(
                id=ev.id,
                material_batch_id=batch.id,
                uploader_id=ev.uploader_id,
                uploader_name=ev.uploader.full_name if ev.uploader else None,
                evidence_type=ev.evidence_type,
                original_filename=ev.original_filename,
                file_size=ev.file_size,
                sha256_hash=ev.sha256_hash,
                notes=ev.notes,
                created_at=ev.created_at,
            )
            for ev in (batch.evidences or [])
        ]

        return MaterialBatchResponse(
            id=batch.id,
            batch_id=batch.batch_id,
            recycler_organization_id=batch.recycler_organization_id,
            recycler_organization_name=batch.recycler_organization.name if batch.recycler_organization else None,
            processor_id=batch.processor_id,
            processor_name=batch.processor.full_name if batch.processor else None,
            material_type=batch.material_type,
            input_weight_kg=batch.input_weight_kg,
            recycled_output_kg=batch.recycled_output_kg,
            residual_kg=batch.residual_kg,
            yield_percentage=batch.yield_percentage,
            allocated_upcycling_weight_kg=batch.allocated_upcycling_weight_kg,
            available_for_upcycling_kg=batch.available_for_upcycling_kg,
            processing_date=batch.processing_date,
            status=batch.status,
            verification_reference=batch.verification_reference,
            material_passport_code=batch.passport.passport_code if getattr(batch, "passport", None) else None,
            notes=batch.notes,
            items=items_resp,
            evidences=ev_resp,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )
