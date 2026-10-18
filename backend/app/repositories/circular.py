"""PLASTIFY Circular Economy Data Access Repositories: Recycling, Upcycling, and Passports."""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.circular import (
    MaterialBatch,
    MaterialBatchEvidence,
    MaterialBatchItem,
    MaterialBatchStatus,
    MaterialPassport,
    Product,
    ProductPassport,
    UpcyclingAllocation,
    UpcyclingBatch,
    UpcyclingBatchEvidence,
    UpcyclingBatchStatus,
)
from app.models.custody import CustodyState
from app.models.logistics import Delivery, DeliveryStatus
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.repositories.base import BaseRepository


class CircularRepository(BaseRepository[MaterialBatch]):
    """Unified repository managing industrial recycling, circular manufacturing, and digital passports."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MaterialBatch, session)

    # --------------------------------------------------------------------------
    # 1. Incoming Verified Raw Materials
    # --------------------------------------------------------------------------

    async def list_incoming_verified_materials(
        self, recycler_org_id: Optional[uuid.UUID] = None
    ) -> List[Tuple[RecoveryEvent, Optional[Delivery], float]]:
        """Fetch verified recovery events eligible for industrial recycling input.

        Returns tuples of (RecoveryEvent, Delivery, already_allocated_weight_kg).
        """
        # Verified recoveries where custody reached VERIFIED or status is VERIFIED
        stmt = (
            select(RecoveryEvent, Delivery)
            .outerjoin(Delivery, Delivery.recovery_id == RecoveryEvent.id)
            .where(
                (RecoveryEvent.status == RecoveryStatus.VERIFIED)
                | (RecoveryEvent.custody_status == CustodyState.VERIFIED.value)
            )
        )

        if recycler_org_id is not None:
            # Deliveries confirmed to this recycler or unassigned open deliveries
            stmt = stmt.where(
                (Delivery.recycler_organization_id == recycler_org_id)
                | (Delivery.recycler_organization_id.is_(None))
            )

        stmt = stmt.order_by(RecoveryEvent.collected_at.asc())
        result = await self.session.execute(stmt)
        rows = result.all()

        incoming: List[Tuple[RecoveryEvent, Optional[Delivery], float]] = []
        for rec, delivery in rows:
            # Calculate already allocated weight in existing material batches
            alloc_stmt = select(func.coalesce(func.sum(MaterialBatchItem.allocated_weight_kg), 0.0)).where(
                MaterialBatchItem.recovery_event_id == rec.id
            )
            alloc_res = await self.session.execute(alloc_stmt)
            already_allocated = float(alloc_res.scalar_one())

            # Verified baseline weight
            verified_weight = rec.weight_kg
            if delivery and delivery.received_weight_kg:
                verified_weight = delivery.received_weight_kg

            available = max(0.0, round(verified_weight - already_allocated, 3))
            if available > 0.001:
                incoming.append((rec, delivery, already_allocated))

        return incoming

    async def get_recovery_allocated_weight(self, recovery_id: uuid.UUID) -> float:
        """Calculate total weight in kg already committed to material batches for a recovery."""
        stmt = select(func.coalesce(func.sum(MaterialBatchItem.allocated_weight_kg), 0.0)).where(
            MaterialBatchItem.recovery_event_id == recovery_id
        )
        res = await self.session.execute(stmt)
        return float(res.scalar_one())

    # --------------------------------------------------------------------------
    # 2. Material Batches (Recycling)
    # --------------------------------------------------------------------------

    async def get_material_batch_by_id(self, batch_id: uuid.UUID) -> Optional[MaterialBatch]:
        """Fetch MaterialBatch with complete relational graphs."""
        stmt = (
            select(MaterialBatch)
            .where(MaterialBatch.id == batch_id)
            .options(
                selectinload(MaterialBatch.recycler_organization),
                selectinload(MaterialBatch.processor),
                selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(MaterialBatch.evidences),
                selectinload(MaterialBatch.allocations),
                selectinload(MaterialBatch.passport),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_material_batch_by_code(self, code: str) -> Optional[MaterialBatch]:
        """Fetch MaterialBatch by unique batch identifier (e.g., 'MB-2026-F981A4')."""
        stmt = (
            select(MaterialBatch)
            .where(MaterialBatch.batch_id == code.strip())
            .options(
                selectinload(MaterialBatch.recycler_organization),
                selectinload(MaterialBatch.processor),
                selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(MaterialBatch.evidences),
                selectinload(MaterialBatch.allocations),
                selectinload(MaterialBatch.passport),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_material_batches(
        self,
        recycler_org_id: Optional[uuid.UUID] = None,
        status: Optional[MaterialBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[MaterialBatch]:
        """List material batches scoped to recycler organization."""
        stmt = select(MaterialBatch)
        if recycler_org_id is not None:
            stmt = stmt.where(MaterialBatch.recycler_organization_id == recycler_org_id)
        if status is not None:
            stmt = stmt.where(MaterialBatch.status == status)

        stmt = (
            stmt.options(
                selectinload(MaterialBatch.recycler_organization),
                selectinload(MaterialBatch.processor),
                selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(MaterialBatch.evidences),
                selectinload(MaterialBatch.allocations),
                selectinload(MaterialBatch.passport),
            )
            .order_by(MaterialBatch.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_material_batch_evidence(
        self, evidence: MaterialBatchEvidence
    ) -> MaterialBatchEvidence:
        """Persist processing evidence for a recycling batch."""
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    async def create_material_passport(
        self, passport: MaterialPassport
    ) -> MaterialPassport:
        """Persist official Material Passport credential."""
        self.session.add(passport)
        await self.session.flush()
        return passport

    async def get_material_passport_by_code(self, code: str) -> Optional[MaterialPassport]:
        """Fetch Material Passport by code."""
        stmt = (
            select(MaterialPassport)
            .where(MaterialPassport.passport_code == code.strip())
            .options(
                selectinload(MaterialPassport.material_batch).selectinload(MaterialBatch.recycler_organization),
                selectinload(MaterialPassport.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(MaterialPassport.issuer_organization),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    # --------------------------------------------------------------------------
    # 3. Upcycling Engine
    # --------------------------------------------------------------------------

    async def list_available_recycled_materials(
        self, material_type: Optional[str] = None
    ) -> List[MaterialBatch]:
        """Fetch completed material batches that have unallocated recycled output remaining."""
        stmt = (
            select(MaterialBatch)
            .where(
                MaterialBatch.status == MaterialBatchStatus.COMPLETED,
                MaterialBatch.recycled_output_kg > 0.0,
            )
            .options(
                selectinload(MaterialBatch.recycler_organization),
                selectinload(MaterialBatch.allocations),
            )
            .order_by(MaterialBatch.created_at.asc())
        )
        if material_type:
            stmt = stmt.where(MaterialBatch.material_type == material_type.strip().upper())

        result = await self.session.execute(stmt)
        batches = list(result.scalars().all())
        # Filter where remaining output > 0
        return [b for b in batches if b.available_for_upcycling_kg > 0.001]

    async def get_material_batch_allocated_weight(self, material_batch_id: uuid.UUID) -> float:
        """Calculate total weight in kg already allocated to upcycling batches for a material batch."""
        stmt = select(func.coalesce(func.sum(UpcyclingAllocation.allocated_weight_kg), 0.0)).where(
            UpcyclingAllocation.material_batch_id == material_batch_id
        )
        res = await self.session.execute(stmt)
        return float(res.scalar_one())

    async def get_material_batch_by_id_for_update(self, batch_id: uuid.UUID) -> Optional[MaterialBatch]:
        """Fetch MaterialBatch by primary key with exclusive row-level lock."""
        stmt = (
            select(MaterialBatch)
            .where(MaterialBatch.id == batch_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_upcycling_batch(self, batch: UpcyclingBatch) -> UpcyclingBatch:
        """Persist new upcycling manufacturing batch."""
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get_upcycling_batch_by_id(self, batch_id: uuid.UUID) -> Optional[UpcyclingBatch]:
        """Fetch UpcyclingBatch with complete dependencies."""
        stmt = (
            select(UpcyclingBatch)
            .where(UpcyclingBatch.id == batch_id)
            .options(
                selectinload(UpcyclingBatch.upcycler_organization),
                selectinload(UpcyclingBatch.creator),
                selectinload(UpcyclingBatch.quality_verifier),
                selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.recycler_organization),
                selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(UpcyclingBatch.products),
                selectinload(UpcyclingBatch.evidences),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_upcycling_batch_by_code(self, code: str) -> Optional[UpcyclingBatch]:
        """Fetch UpcyclingBatch by batch identifier code (e.g. 'UPC-2026-B3C4D5')."""
        stmt = (
            select(UpcyclingBatch)
            .where(UpcyclingBatch.batch_id == code.strip())
            .options(
                selectinload(UpcyclingBatch.upcycler_organization),
                selectinload(UpcyclingBatch.creator),
                selectinload(UpcyclingBatch.quality_verifier),
                selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.recycler_organization),
                selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery),
                selectinload(UpcyclingBatch.products),
                selectinload(UpcyclingBatch.evidences),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_upcycling_batches(
        self,
        upcycler_org_id: Optional[uuid.UUID] = None,
        status: Optional[UpcyclingBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[UpcyclingBatch]:
        """List upcycling batches filtered by upcycler organization."""
        stmt = select(UpcyclingBatch)
        if upcycler_org_id is not None:
            stmt = stmt.where(UpcyclingBatch.upcycler_organization_id == upcycler_org_id)
        if status is not None:
            stmt = stmt.where(UpcyclingBatch.status == status)

        stmt = (
            stmt.options(
                selectinload(UpcyclingBatch.upcycler_organization),
                selectinload(UpcyclingBatch.creator),
                selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch),
                selectinload(UpcyclingBatch.products),
                selectinload(UpcyclingBatch.evidences),
            )
            .order_by(UpcyclingBatch.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_upcycling_batch_evidence(
        self, evidence: UpcyclingBatchEvidence
    ) -> UpcyclingBatchEvidence:
        """Persist manufacturing/QA evidence for an upcycling batch."""
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    # --------------------------------------------------------------------------
    # 4. Products and Product Passports
    # --------------------------------------------------------------------------

    async def create_product(self, product: Product) -> Product:
        """Persist finished circular product."""
        self.session.add(product)
        await self.session.flush()
        return product

    async def get_product_by_id(self, product_id: uuid.UUID) -> Optional[Product]:
        """Fetch Product by primary key."""
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.organization),
                selectinload(Product.upcycling_batch),
                selectinload(Product.passports),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_product_by_code(self, code: str) -> Optional[Product]:
        """Fetch Product by unique product code."""
        stmt = (
            select(Product)
            .where(Product.product_code == code.strip())
            .options(
                selectinload(Product.organization),
                selectinload(Product.upcycling_batch),
                selectinload(Product.passports),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_product_passport(self, passport: ProductPassport) -> ProductPassport:
        """Persist QR-ready Digital Product Passport."""
        self.session.add(passport)
        await self.session.flush()
        return passport

    async def get_product_passport_by_identifier(
        self, passport_id: str
    ) -> Optional[ProductPassport]:
        """Retrieve ProductPassport by QR-ready public identifier with deep provenance links."""
        stmt = (
            select(ProductPassport)
            .where(ProductPassport.passport_id == passport_id.strip())
            .options(
                selectinload(ProductPassport.product).selectinload(Product.organization),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.upcycler_organization),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.creator),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.recycler_organization),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery).selectinload(RecoveryEvent.program),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery).selectinload(RecoveryEvent.collector_organization),
                selectinload(ProductPassport.upcycling_batch).selectinload(UpcyclingBatch.allocations).selectinload(UpcyclingAllocation.material_batch).selectinload(MaterialBatch.items).selectinload(MaterialBatchItem.recovery).selectinload(RecoveryEvent.verification_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
