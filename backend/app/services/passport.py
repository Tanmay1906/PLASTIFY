"""PLASTIFY Digital Product Passport (DPP) Domain Service.

Provides complete, tamper-evident public provenance connecting:
    Product -> Upcycling Batch -> Material Batch -> Recovery Event(s)
With strict segregation of mass metrics:
    collected, delivered, verified, recycled output, upcycled material, residual.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select

from app.core.exceptions import NotFoundException
from app.models.circular import ProductPassport
from app.models.logistics import Delivery
from app.models.verification import VerificationRecord
from app.repositories.circular import CircularRepository
from app.schemas.circular import (
    MassAccountingSummary,
    MaterialBatchResponse,
    ProductPassportProvenanceResponse,
    ProductResponse,
    SourceRecoverySummary,
    UpcyclingBatchResponse,
)
from app.services.base import BaseService

logger = logging.getLogger("plastify.services.passport")


class PassportService(BaseService):
    """Domain service resolving QR-ready Digital Product Passports and provenance trails."""

    def __init__(self, circular_repo: CircularRepository) -> None:
        super().__init__()
        self.circular_repo = circular_repo

    async def get_product_passport_provenance(
        self, passport_id: str
    ) -> ProductPassportProvenanceResponse:
        """Resolve full cryptographic circular provenance from a public QR-ready passport ID.

        Publicly accessible without authentication to empower consumers, brands, and auditors.
        """
        passport = await self.circular_repo.get_product_passport_by_identifier(passport_id)
        if not passport:
            raise NotFoundException(
                f"Digital Product Passport '{passport_id}' was not found.",
                error_code="PASSPORT_NOT_FOUND",
            )

        product = passport.product
        upcycling_batch = passport.upcycling_batch

        # 1. Collect all upstream MaterialBatches and Source Recoveries
        material_batches: List[MaterialBatchResponse] = []
        source_recoveries: List[SourceRecoverySummary] = []
        seen_recovery_ids = set()

        total_collected_kg = 0.0
        total_delivered_kg = 0.0
        total_verified_kg = 0.0
        total_recycled_output_kg = 0.0
        total_residual_kg = 0.0
        total_upcycled_material_kg = round(upcycling_batch.total_input_material_kg, 3)

        for allocation in upcycling_batch.allocations:
            mat_batch = allocation.material_batch
            if not mat_batch:
                continue

            total_recycled_output_kg += mat_batch.recycled_output_kg
            total_residual_kg += mat_batch.residual_kg

            # Add material batch response
            mat_items_resp = []
            for item in mat_batch.items:
                rec = item.recovery
                if not rec:
                    continue

                if rec.id not in seen_recovery_ids:
                    seen_recovery_ids.add(rec.id)
                    total_collected_kg += rec.weight_kg

                    # Lookup verification code and verified weight if available
                    v_code = None
                    v_weight = rec.weight_kg
                    if rec.verification_records and len(rec.verification_records) > 0:
                        v_code = rec.verification_records[0].verification_code
                        if rec.verification_records[0].verified_weight_kg is not None:
                            v_weight = rec.verification_records[0].verified_weight_kg
                    else:
                        v_stmt = (
                            select(VerificationRecord)
                            .where(VerificationRecord.recovery_id == rec.id)
                            .order_by(VerificationRecord.created_at.desc())
                        )
                        v_res = await self.circular_repo.session.execute(v_stmt)
                        v_rec = v_res.scalars().first()
                        if v_rec:
                            v_code = v_rec.verification_code
                            if v_rec.verified_weight_kg is not None:
                                v_weight = v_rec.verified_weight_kg

                    total_verified_kg += v_weight

                    # Lookup physical delivery record for segregated delivered weight
                    deliv_stmt = (
                        select(Delivery)
                        .where(Delivery.recovery_id == rec.id)
                        .order_by(Delivery.created_at.desc())
                    )
                    deliv_res = await self.circular_repo.session.execute(deliv_stmt)
                    deliv = deliv_res.scalars().first()
                    deliv_weight = (
                        deliv.delivered_weight_kg
                        if (deliv and deliv.delivered_weight_kg is not None)
                        else v_weight
                    )
                    total_delivered_kg += deliv_weight

                    source_recoveries.append(
                        SourceRecoverySummary(
                            recovery_id=rec.id,
                            recovery_human_id=rec.recovery_id,
                            material_type=rec.material_type,
                            collected_weight_kg=rec.weight_kg,
                            verified_weight_kg=v_weight,
                            allocated_to_batch_kg=item.allocated_weight_kg,
                            collection_location=rec.collection_location,
                            collection_coordinates=rec.collection_coordinates,
                            collected_at=rec.collected_at,
                            collector_organization_name=rec.collector_organization.name
                            if rec.collector_organization
                            else None,
                            program_name=rec.program.name if rec.program else None,
                            verification_code=v_code,
                        )
                    )

            # Build MaterialBatchResponse
            material_batches.append(
                MaterialBatchResponse(
                    id=mat_batch.id,
                    batch_id=mat_batch.batch_id,
                    recycler_organization_id=mat_batch.recycler_organization_id,
                    recycler_organization_name=mat_batch.recycler_organization.name
                    if mat_batch.recycler_organization
                    else None,
                    processor_id=mat_batch.processor_id,
                    processor_name=mat_batch.processor.full_name if mat_batch.processor else None,
                    material_type=mat_batch.material_type,
                    input_weight_kg=mat_batch.input_weight_kg,
                    recycled_output_kg=mat_batch.recycled_output_kg,
                    residual_kg=mat_batch.residual_kg,
                    yield_percentage=mat_batch.yield_percentage,
                    allocated_upcycling_weight_kg=mat_batch.allocated_upcycling_weight_kg,
                    available_for_upcycling_kg=mat_batch.available_for_upcycling_kg,
                    processing_date=mat_batch.processing_date,
                    status=mat_batch.status,
                    verification_reference=mat_batch.verification_reference,
                    notes=mat_batch.notes,
                    items=[],
                    evidences=[],
                    created_at=mat_batch.created_at,
                    updated_at=mat_batch.updated_at,
                )
            )

        # Calculate overall recovery yield
        yield_pct = 0.0
        if total_verified_kg > 0.0:
            yield_pct = round((total_recycled_output_kg / total_verified_kg) * 100.0, 2)

        mass_accounting = MassAccountingSummary(
            collected_weight_kg=round(total_collected_kg, 3),
            delivered_weight_kg=round(total_delivered_kg, 3),
            verified_weight_kg=round(total_verified_kg, 3),
            recycled_output_kg=round(total_recycled_output_kg, 3),
            upcycled_material_kg=round(total_upcycled_material_kg, 3),
            residual_kg=round(total_residual_kg, 3),
            overall_recovery_yield_pct=yield_pct,
        )

        product_resp = ProductResponse(
            id=product.id,
            product_code=product.product_code,
            sku=product.sku,
            name=product.name,
            description=product.description,
            product_type=product.product_type,
            organization_id=product.organization_id,
            organization_name=product.organization.name if product.organization else None,
            upcycling_batch_id=product.upcycling_batch_id,
            upcycling_batch_code=upcycling_batch.batch_id,
            weight_per_unit_kg=product.weight_per_unit_kg,
            recycled_content_percentage=product.recycled_content_percentage,
            is_active=product.is_active,
            created_at=product.created_at,
        )

        upcycling_batch_resp = UpcyclingBatchResponse(
            id=upcycling_batch.id,
            batch_id=upcycling_batch.batch_id,
            upcycler_organization_id=upcycling_batch.upcycler_organization_id,
            upcycler_organization_name=upcycling_batch.upcycler_organization.name
            if upcycling_batch.upcycler_organization
            else None,
            creator_id=upcycling_batch.creator_id,
            creator_name=upcycling_batch.creator.full_name if upcycling_batch.creator else None,
            product_type=upcycling_batch.product_type,
            total_input_material_kg=upcycling_batch.total_input_material_kg,
            quantity_produced=upcycling_batch.quantity_produced,
            unit_of_measure=upcycling_batch.unit_of_measure,
            quality_verified=upcycling_batch.quality_verified,
            quality_rating=upcycling_batch.quality_rating,
            quality_notes=upcycling_batch.quality_notes,
            quality_verified_at=upcycling_batch.quality_verified_at,
            status=upcycling_batch.status,
            notes=upcycling_batch.notes,
            allocations=[],
            evidences=[],
            created_at=upcycling_batch.created_at,
            updated_at=upcycling_batch.updated_at,
        )

        return ProductPassportProvenanceResponse(
            passport_id=passport.passport_id,
            qr_ready_identifier=passport.passport_id,
            qr_code_url=passport.qr_code_url,
            public_url=passport.public_url,
            product=product_resp,
            upcycling_batch=upcycling_batch_resp,
            material_batches=material_batches,
            source_recoveries=source_recoveries,
            mass_accounting=mass_accounting,
            issued_at=passport.created_at,
        )
