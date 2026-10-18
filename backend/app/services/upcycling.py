"""PLASTIFY Upcycling Manufacturing Domain Service.

Connects:
    Product -> Upcycling Batch -> Material Batch(es) -> Recovery Event(s)
Manages circular product fabrication, quality specifications, and digital product passports.
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
    MaterialBatchStatus,
    Product,
    ProductPassport,
    UpcyclingAllocation,
    UpcyclingBatch,
    UpcyclingBatchEvidence,
    UpcyclingBatchStatus,
)
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.circular import CircularRepository
from app.schemas.circular import (
    AvailableRecycledMaterialResponse,
    ProductCreateRequest,
    ProductResponse,
    UpcyclingAllocationResponse,
    UpcyclingBatchCompleteRequest,
    UpcyclingBatchCreateRequest,
    UpcyclingBatchEvidenceResponse,
    UpcyclingBatchResponse,
    UpcyclingQualityUpdateRequest,
)
from app.services.base import BaseService

logger = logging.getLogger("plastify.services.upcycling")


class UpcyclingService(BaseService):
    """Domain service managing upcycling batches, quality verification, and product passport generation."""

    def __init__(
        self,
        circular_repo: CircularRepository,
        audit_repo: AuditRepository,
        storage_service: IStorageService,
        settings: Settings,
    ) -> None:
        super().__init__()
        self.circular_repo = circular_repo
        self.audit_repo = audit_repo
        self.storage_service = storage_service
        self.settings = settings

    # --------------------------------------------------------------------------
    # 1. Available Recycled Materials
    # --------------------------------------------------------------------------

    async def list_available_materials(
        self, requester: User, material_type: Optional[str] = None
    ) -> List[AvailableRecycledMaterialResponse]:
        """Fetch available completed recycled material batches eligible for upcycling."""
        batches = await self.circular_repo.list_available_recycled_materials(material_type)
        return [
            AvailableRecycledMaterialResponse(
                material_batch_id=b.id,
                batch_id=b.batch_id,
                recycler_organization_name=b.recycler_organization.name if b.recycler_organization else "Certified Recycler",
                material_type=b.material_type,
                recycled_output_kg=b.recycled_output_kg,
                allocated_upcycling_weight_kg=b.allocated_upcycling_weight_kg,
                available_weight_kg=b.available_for_upcycling_kg,
                processing_date=b.processing_date,
            )
            for b in batches
        ]

    # --------------------------------------------------------------------------
    # 2. Create Upcycling Batch
    # --------------------------------------------------------------------------

    async def create_upcycling_batch(
        self, data: UpcyclingBatchCreateRequest, requester: User
    ) -> UpcyclingBatchResponse:
        """Create a new upcycling manufacturing batch drawing from completed MaterialBatches."""
        if requester.role not in [UserRole.UPCYCLER, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only certified Upcyclers or Super Admins can create upcycling batches.")

        target_org_id = requester.organization_id
        if not target_org_id and requester.role != UserRole.SUPER_ADMIN:
            raise ForbiddenException("Upcycler must belong to an active organization.")

        total_input_kg = 0.0
        allocations: List[UpcyclingAllocation] = []

        for alloc_in in data.material_allocations:
            batch = await self.circular_repo.get_material_batch_by_id(alloc_in.material_batch_id)
            if not batch:
                raise NotFoundException(f"Material batch '{alloc_in.material_batch_id}' was not found.")

            if batch.status != MaterialBatchStatus.COMPLETED:
                raise BadRequestException(
                    f"Material batch '{batch.batch_id}' is not COMPLETED. "
                    "Only fully processed and certified recycled batches can be allocated to upcycling."
                )

            # Check unallocated available weight against DB allocations
            already_alloc = await self.circular_repo.get_material_batch_allocated_weight(batch.id)
            avail = max(0.0, round(batch.recycled_output_kg - already_alloc, 3))
            if alloc_in.allocated_weight_kg > avail + 0.001:
                raise BadRequestException(
                    f"Over-allocation error on material batch '{batch.batch_id}': Requested {alloc_in.allocated_weight_kg} kg, "
                    f"but only {avail} kg recycled output remains available."
                )

            total_input_kg += alloc_in.allocated_weight_kg
            allocations.append(
                UpcyclingAllocation(
                    material_batch_id=batch.id,
                    allocated_weight_kg=round(alloc_in.allocated_weight_kg, 3),
                )
            )

        total_input_kg = round(total_input_kg, 3)
        if total_input_kg <= 0.0:
            raise BadRequestException("Total input material weight must be greater than zero.")

        year = datetime.now(timezone.utc).year
        batch_code = f"UPC-{year}-{uuid.uuid4().hex[:8].upper()}"

        upcycling_batch = UpcyclingBatch(
            batch_id=batch_code,
            upcycler_organization_id=target_org_id,
            creator_id=requester.id,
            product_type=data.product_type.strip(),
            total_input_material_kg=total_input_kg,
            quantity_produced=0,
            unit_of_measure=data.unit_of_measure.strip().upper(),
            status=UpcyclingBatchStatus.CREATED,
            notes=data.notes.strip() if data.notes else None,
            metadata_json=data.metadata or {},
        )
        upcycling_batch.allocations.extend(allocations)

        created_batch = await self.circular_repo.create_upcycling_batch(upcycling_batch)

        await self.audit_repo.record(
            action="UPCYCLING_BATCH_CREATED",
            resource=f"upcycling_batch:{created_batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch_code,
                "product_type": data.product_type,
                "total_input_kg": total_input_kg,
                "allocations_count": len(allocations),
            },
        )

        logger.info(f"Upcycling Batch {batch_code} ({data.product_type}, {total_input_kg}kg) created by {requester.email}")

        refreshed = await self.circular_repo.get_upcycling_batch_by_id(created_batch.id)
        return self._build_upcycling_batch_response(refreshed or created_batch)

    # --------------------------------------------------------------------------
    # 3. Quality Verification & Evidence
    # --------------------------------------------------------------------------

    async def update_quality(
        self,
        batch_id: uuid.UUID,
        data: UpcyclingQualityUpdateRequest,
        requester: User,
    ) -> UpcyclingBatchResponse:
        """Record quality assurance verification and grading for an upcycling batch."""
        batch = await self.circular_repo.get_upcycling_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Upcycling batch not found.")

        self._assert_batch_ownership(batch, requester)

        batch.quality_verified = data.quality_verified
        if data.quality_rating:
            batch.quality_rating = data.quality_rating.strip().upper()
        if data.quality_notes:
            batch.quality_notes = data.quality_notes.strip()

        batch.quality_verified_by_id = requester.id
        batch.quality_verified_at = datetime.now(timezone.utc)

        await self.circular_repo.session.flush()

        await self.audit_repo.record(
            action="UPCYCLING_QUALITY_VERIFIED",
            resource=f"upcycling_batch:{batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch.batch_id,
                "quality_verified": data.quality_verified,
                "rating": data.quality_rating,
            },
        )

        logger.info(f"Quality updated for Upcycling Batch {batch.batch_id}: verified={data.quality_verified}")
        refreshed = await self.circular_repo.get_upcycling_batch_by_id(batch.id)
        return self._build_upcycling_batch_response(refreshed or batch)

    async def upload_evidence(
        self,
        batch_id: uuid.UUID,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        evidence_type: str,
        notes: Optional[str],
        requester: User,
    ) -> UpcyclingBatchEvidenceResponse:
        """Upload factory, specification, or testing documentation for an upcycling batch."""
        batch = await self.circular_repo.get_upcycling_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Upcycling batch not found.")

        self._assert_batch_ownership(batch, requester)

        clean_filename = filename.strip()
        safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean_filename)
        storage_key = f"circular/upcycling_batches/{batch.id}/{uuid.uuid4().hex}_{safe_name}"

        self.storage_service.upload_file(
            file_content=file_bytes,
            storage_key=storage_key,
            content_type=mime_type,
        )

        sha256 = hashlib.sha256(file_bytes).hexdigest()

        evidence = UpcyclingBatchEvidence(
            upcycling_batch_id=batch.id,
            uploader_id=requester.id,
            evidence_type=evidence_type.strip().upper(),
            storage_key=storage_key,
            original_filename=clean_filename,
            mime_type=mime_type,
            file_size=len(file_bytes),
            sha256_hash=sha256,
            notes=notes.strip() if notes else None,
        )
        created_ev = await self.circular_repo.add_upcycling_batch_evidence(evidence)

        logger.info(f"Evidence '{created_ev.id}' attached to Upcycling Batch {batch.batch_id}")
        return UpcyclingBatchEvidenceResponse(
            id=created_ev.id,
            upcycling_batch_id=batch.id,
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
    # 4. Complete Upcycling Batch
    # --------------------------------------------------------------------------

    async def complete_upcycling_batch(
        self,
        batch_id: uuid.UUID,
        data: UpcyclingBatchCompleteRequest,
        requester: User,
    ) -> UpcyclingBatchResponse:
        """Finalize upcycling production batch and record final finished product count."""
        batch = await self.circular_repo.get_upcycling_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Upcycling batch not found.")

        self._assert_batch_ownership(batch, requester)

        if batch.status == UpcyclingBatchStatus.COMPLETED:
            raise BadRequestException("Upcycling batch is already COMPLETED.")

        if data.quantity_produced <= 0:
            raise BadRequestException("Quantity produced must be at least 1 unit.")

        batch.quantity_produced = data.quantity_produced
        batch.status = UpcyclingBatchStatus.COMPLETED
        if data.notes:
            batch.notes = data.notes.strip()

        await self.circular_repo.session.flush()

        await self.audit_repo.record(
            action="UPCYCLING_BATCH_COMPLETED",
            resource=f"upcycling_batch:{batch.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "batch_id": batch.batch_id,
                "quantity_produced": data.quantity_produced,
                "unit_of_measure": batch.unit_of_measure,
            },
        )

        logger.info(f"Upcycling Batch {batch.batch_id} COMPLETED: {data.quantity_produced} {batch.unit_of_measure} produced")

        refreshed = await self.circular_repo.get_upcycling_batch_by_id(batch.id)
        return self._build_upcycling_batch_response(refreshed or batch)

    # --------------------------------------------------------------------------
    # 5. Product & Product Passport Registration
    # --------------------------------------------------------------------------

    async def register_product(
        self,
        batch_id: uuid.UUID,
        data: ProductCreateRequest,
        requester: User,
    ) -> ProductResponse:
        """Register a commercial product under this upcycling batch and generate a QR-ready Product Passport."""
        batch = await self.circular_repo.get_upcycling_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Upcycling batch not found.")

        self._assert_batch_ownership(batch, requester)

        year = datetime.now(timezone.utc).year
        product_code = f"PRD-{year}-{uuid.uuid4().hex[:8].upper()}"

        product = Product(
            product_code=product_code,
            sku=data.sku.strip() if data.sku else None,
            name=data.name.strip(),
            description=data.description.strip() if data.description else None,
            product_type=batch.product_type,
            organization_id=batch.upcycler_organization_id,
            upcycling_batch_id=batch.id,
            weight_per_unit_kg=data.weight_per_unit_kg,
            recycled_content_percentage=data.recycled_content_percentage,
            is_active=True,
            metadata_json=data.metadata or {},
        )
        created_product = await self.circular_repo.create_product(product)

        # Generate QR-ready Digital Product Passport
        passport_id = f"PP-{year}-{uuid.uuid4().hex[:10].upper()}"
        public_url = f"/api/v1/passports/product/{passport_id}"
        qr_url = f"https://api.plastify.io/v1/passports/product/{passport_id}"

        passport = ProductPassport(
            passport_id=passport_id,
            product_id=created_product.id,
            upcycling_batch_id=batch.id,
            qr_code_url=qr_url,
            public_url=public_url,
            is_public=True,
            metadata_json={
                "product_code": product_code,
                "batch_id": batch.batch_id,
                "recycled_content_pct": data.recycled_content_percentage,
                "issued_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.circular_repo.create_product_passport(passport)

        await self.audit_repo.record(
            action="PRODUCT_PASSPORT_ISSUED",
            resource=f"product_passport:{passport_id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "product_code": product_code,
                "passport_id": passport_id,
                "upcycling_batch_id": batch.batch_id,
            },
        )

        logger.info(f"Product '{created_product.name}' ({product_code}) registered. Passport ID: {passport_id}")

        refreshed = await self.circular_repo.get_product_by_id(created_product.id)
        return self._build_product_response(refreshed or created_product)

    # --------------------------------------------------------------------------
    # 6. Retrieve Upcycling Batches
    # --------------------------------------------------------------------------

    async def get_upcycling_batch(
        self, batch_id: uuid.UUID, requester: User
    ) -> UpcyclingBatchResponse:
        """Fetch UpcyclingBatch by primary key."""
        batch = await self.circular_repo.get_upcycling_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Upcycling batch not found.")

        self._assert_can_view_batch(batch, requester)
        return self._build_upcycling_batch_response(batch)

    async def list_upcycling_batches(
        self,
        requester: User,
        status: Optional[UpcyclingBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[UpcyclingBatchResponse]:
        """List upcycling batches scoped to requester's organization."""
        target_org = requester.organization_id if requester.role != UserRole.SUPER_ADMIN else None
        batches = await self.circular_repo.list_upcycling_batches(
            upcycler_org_id=target_org,
            status=status,
            skip=skip,
            limit=limit,
        )
        return [self._build_upcycling_batch_response(b) for b in batches]

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------

    def _assert_batch_ownership(self, batch: UpcyclingBatch, user: User) -> None:
        if user.role == UserRole.SUPER_ADMIN:
            return
        if not user.organization_id or user.organization_id != batch.upcycler_organization_id:
            raise ForbiddenException("Access denied: You do not have permission to manage this upcycling batch.")

    def _assert_can_view_batch(self, batch: UpcyclingBatch, user: User) -> None:
        if user.role in [UserRole.SUPER_ADMIN, UserRole.AUDITOR, UserRole.VERIFIER]:
            return
        if user.organization_id and user.organization_id == batch.upcycler_organization_id:
            return
        raise ForbiddenException("Access denied: You do not have permission to view this upcycling batch.")

    def _build_upcycling_batch_response(self, batch: UpcyclingBatch) -> UpcyclingBatchResponse:
        alloc_resp = [
            UpcyclingAllocationResponse(
                id=a.id,
                material_batch_id=a.material_batch_id,
                material_batch_code=a.material_batch.batch_id if a.material_batch else "Unknown",
                material_type=a.material_batch.material_type if a.material_batch else "PLASTIC",
                allocated_weight_kg=a.allocated_weight_kg,
                recycler_organization_name=a.material_batch.recycler_organization.name
                if a.material_batch and a.material_batch.recycler_organization
                else None,
            )
            for a in (batch.allocations or [])
        ]

        ev_resp = [
            UpcyclingBatchEvidenceResponse(
                id=ev.id,
                upcycling_batch_id=batch.id,
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

        return UpcyclingBatchResponse(
            id=batch.id,
            batch_id=batch.batch_id,
            upcycler_organization_id=batch.upcycler_organization_id,
            upcycler_organization_name=batch.upcycler_organization.name if batch.upcycler_organization else None,
            creator_id=batch.creator_id,
            creator_name=batch.creator.full_name if batch.creator else None,
            product_type=batch.product_type,
            total_input_material_kg=batch.total_input_material_kg,
            quantity_produced=batch.quantity_produced,
            unit_of_measure=batch.unit_of_measure,
            quality_verified=batch.quality_verified,
            quality_rating=batch.quality_rating,
            quality_notes=batch.quality_notes,
            quality_verified_at=batch.quality_verified_at,
            status=batch.status,
            notes=batch.notes,
            allocations=alloc_resp,
            evidences=ev_resp,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    def _build_product_response(self, product: Product) -> ProductResponse:
        passport_id = None
        qr_code_url = None
        if product.passports and len(product.passports) > 0:
            passport_id = product.passports[0].passport_id
            qr_code_url = product.passports[0].qr_code_url

        return ProductResponse(
            id=product.id,
            product_code=product.product_code,
            sku=product.sku,
            name=product.name,
            description=product.description,
            product_type=product.product_type,
            organization_id=product.organization_id,
            organization_name=product.organization.name if product.organization else None,
            upcycling_batch_id=product.upcycling_batch_id,
            upcycling_batch_code=product.upcycling_batch.batch_id if product.upcycling_batch else None,
            weight_per_unit_kg=product.weight_per_unit_kg,
            recycled_content_percentage=product.recycled_content_percentage,
            passport_id=passport_id,
            qr_code_url=qr_code_url,
            is_active=product.is_active,
            created_at=product.created_at,
        )
