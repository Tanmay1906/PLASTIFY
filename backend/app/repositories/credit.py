"""PLASTIFY Credit Batch, Plastic Credit, Transaction, and Retirement Repositories."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.credit import (
    CreditBatch,
    CreditBatchStatus,
    CreditRetirement,
    CreditStatus,
    CreditTransaction,
    PlasticCredit,
    TransactionType,
)
from app.repositories.base import BaseRepository


class CreditRepository(BaseRepository[CreditBatch]):
    """Data access repository for credit issuance batches, credits, transactions, and retirements."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CreditBatch, session)

    # --------------------------------------------------------------------------
    # 1. Credit Batches
    # --------------------------------------------------------------------------

    async def get_batch_by_id(self, batch_id: uuid.UUID) -> Optional[CreditBatch]:
        """Fetch credit batch by UUID with all relations."""
        stmt = (
            select(CreditBatch)
            .where(CreditBatch.id == batch_id)
            .options(
                selectinload(CreditBatch.organization),
                selectinload(CreditBatch.methodology_version),
                selectinload(CreditBatch.creator),
                selectinload(CreditBatch.approver),
                selectinload(CreditBatch.issuer),
                selectinload(CreditBatch.impact_allocations),
                selectinload(CreditBatch.credits),
                selectinload(CreditBatch.retirements),
                selectinload(CreditBatch.transactions),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_batch_by_id_for_update(self, batch_id: uuid.UUID) -> Optional[CreditBatch]:
        """Fetch credit batch with exclusive row lock to protect concurrency."""
        stmt = (
            select(CreditBatch)
            .where(CreditBatch.id == batch_id)
            .with_for_update()
            .options(
                selectinload(CreditBatch.organization),
                selectinload(CreditBatch.methodology_version),
                selectinload(CreditBatch.impact_allocations),
                selectinload(CreditBatch.credits),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_batch_by_number(self, batch_number: str) -> Optional[CreditBatch]:
        """Fetch credit batch by unique batch number (e.g. CRB-2026-MUM-0001)."""
        stmt = (
            select(CreditBatch)
            .where(CreditBatch.batch_number == batch_number.strip().upper())
            .options(
                selectinload(CreditBatch.organization),
                selectinload(CreditBatch.methodology_version),
                selectinload(CreditBatch.impact_allocations),
                selectinload(CreditBatch.credits),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_batch_by_idempotency_key(self, idempotency_key: str) -> Optional[CreditBatch]:
        """Fetch credit batch by unique idempotency key."""
        stmt = (
            select(CreditBatch)
            .where(CreditBatch.idempotency_key == idempotency_key.strip())
            .options(
                selectinload(CreditBatch.organization),
                selectinload(CreditBatch.credits),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_batches(
        self,
        organization_id: Optional[uuid.UUID] = None,
        status: Optional[CreditBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CreditBatch]:
        """List credit batches with organization filter and pagination."""
        stmt = select(CreditBatch)
        if organization_id:
            stmt = stmt.where(CreditBatch.organization_id == organization_id)
        if status:
            stmt = stmt.where(CreditBatch.status == status)

        stmt = (
            stmt.options(
                selectinload(CreditBatch.organization),
                selectinload(CreditBatch.methodology_version),
                selectinload(CreditBatch.creator),
                selectinload(CreditBatch.issuer),
            )
            .order_by(CreditBatch.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_batches(
        self,
        organization_id: Optional[uuid.UUID] = None,
        status: Optional[CreditBatchStatus] = None,
    ) -> int:
        """Count total matching credit batches."""
        stmt = select(func.count(CreditBatch.id))
        if organization_id:
            stmt = stmt.where(CreditBatch.organization_id == organization_id)
        if status:
            stmt = stmt.where(CreditBatch.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar_one())

    async def create_batch(self, batch: CreditBatch) -> CreditBatch:
        """Persist a new credit batch."""
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def generate_next_batch_number(self, vintage_year: int, prefix: str = "CRB") -> str:
        """Generate unique batch number (e.g. CRB-2026-F981A4B2)."""
        suffix = uuid.uuid4().hex[:8].upper()
        return f"{prefix}-{vintage_year}-{suffix}"

    # --------------------------------------------------------------------------
    # 2. Plastic Credits (Serialized)
    # --------------------------------------------------------------------------

    async def get_credit_by_id(self, credit_id: uuid.UUID) -> Optional[PlasticCredit]:
        """Fetch serialized plastic credit by UUID."""
        stmt = (
            select(PlasticCredit)
            .where(PlasticCredit.id == credit_id)
            .options(
                selectinload(PlasticCredit.credit_batch),
                selectinload(PlasticCredit.owner_organization),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_credit_by_id_for_update(self, credit_id: uuid.UUID) -> Optional[PlasticCredit]:
        """Fetch serialized credit with row lock for transfer/retirement."""
        stmt = (
            select(PlasticCredit)
            .where(PlasticCredit.id == credit_id)
            .with_for_update()
            .options(
                selectinload(PlasticCredit.credit_batch),
                selectinload(PlasticCredit.owner_organization),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_credit_by_serial(self, serial: str) -> Optional[PlasticCredit]:
        """Fetch credit by unique serial number."""
        stmt = (
            select(PlasticCredit)
            .where(PlasticCredit.serial_number == serial.strip().upper())
            .options(
                selectinload(PlasticCredit.credit_batch),
                selectinload(PlasticCredit.owner_organization),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_credits(
        self,
        owner_organization_id: Optional[uuid.UUID] = None,
        status: Optional[CreditStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[PlasticCredit]:
        """List serialized credits with owner filtering."""
        stmt = select(PlasticCredit)
        if owner_organization_id:
            stmt = stmt.where(PlasticCredit.owner_organization_id == owner_organization_id)
        if status:
            stmt = stmt.where(PlasticCredit.status == status)

        stmt = (
            stmt.options(
                selectinload(PlasticCredit.credit_batch),
                selectinload(PlasticCredit.owner_organization),
            )
            .order_by(PlasticCredit.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_credits(self, credits: List[PlasticCredit]) -> List[PlasticCredit]:
        """Persist a list of serialized credits."""
        for c in credits:
            self.session.add(c)
        await self.session.flush()
        return credits

    # --------------------------------------------------------------------------
    # 3. Credit Transactions
    # --------------------------------------------------------------------------

    async def create_transaction(self, tx: CreditTransaction) -> CreditTransaction:
        """Persist a credit transaction."""
        self.session.add(tx)
        await self.session.flush()
        return tx

    async def list_transactions_by_batch(self, batch_id: uuid.UUID) -> List[CreditTransaction]:
        """List transaction audit log for a credit batch."""
        stmt = (
            select(CreditTransaction)
            .where(CreditTransaction.credit_batch_id == batch_id)
            .options(
                selectinload(CreditTransaction.from_organization),
                selectinload(CreditTransaction.to_organization),
                selectinload(CreditTransaction.actor),
            )
            .order_by(CreditTransaction.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --------------------------------------------------------------------------
    # 4. Credit Retirements
    # --------------------------------------------------------------------------

    async def get_retirement_by_id(self, retirement_id: uuid.UUID) -> Optional[CreditRetirement]:
        """Fetch retirement record by primary key."""
        stmt = (
            select(CreditRetirement)
            .where(CreditRetirement.id == retirement_id)
            .options(
                selectinload(CreditRetirement.credit_batch),
                selectinload(CreditRetirement.retiring_organization),
                selectinload(CreditRetirement.actor),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_retirement_by_certificate_id(self, certificate_id: str) -> Optional[CreditRetirement]:
        """Fetch retirement by unique public certificate ID."""
        stmt = (
            select(CreditRetirement)
            .where(CreditRetirement.certificate_id == certificate_id.strip().upper())
            .options(
                selectinload(CreditRetirement.credit_batch),
                selectinload(CreditRetirement.retiring_organization),
                selectinload(CreditRetirement.actor),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_retirement_by_idempotency_key(self, idempotency_key: str) -> Optional[CreditRetirement]:
        """Check for existing retirement by client idempotency key."""
        stmt = (
            select(CreditRetirement)
            .where(CreditRetirement.idempotency_key == idempotency_key.strip())
            .options(
                selectinload(CreditRetirement.credit_batch),
                selectinload(CreditRetirement.retiring_organization),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_retirements(
        self,
        retiring_organization_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CreditRetirement]:
        """List retirement records."""
        stmt = select(CreditRetirement)
        if retiring_organization_id:
            stmt = stmt.where(CreditRetirement.retiring_organization_id == retiring_organization_id)
        stmt = (
            stmt.options(
                selectinload(CreditRetirement.credit_batch),
                selectinload(CreditRetirement.retiring_organization),
                selectinload(CreditRetirement.actor),
            )
            .order_by(CreditRetirement.retired_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_retirement(self, ret: CreditRetirement) -> CreditRetirement:
        """Persist a new credit retirement."""
        self.session.add(ret)
        await self.session.flush()
        return ret

    async def generate_next_retirement_id(self, year: int) -> str:
        """Generate unique retirement code."""
        return f"RET-{year}-{uuid.uuid4().hex[:8].upper()}"

    async def generate_next_certificate_id(self, year: int) -> str:
        """Generate unique public certificate identifier."""
        return f"CERT-RET-{year}-{uuid.uuid4().hex[:12].upper()}"
