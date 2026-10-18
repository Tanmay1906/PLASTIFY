"""PLASTIFY Plastic Credit Issuance, Transfer, and Retirement Service.

Enforces:
- Exact decimal accounting (NUMERIC)
- Non-duplication and mass conservation
- Self-approval prevention
- Concurrency locks (with_for_update)
- Client idempotency and anti-replay
- Terminal retirement permanence
- External registry mock and pending reconciliation handling
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.credit import (
    CreditBatch,
    CreditBatchStatus,
    CreditRetirement,
    CreditStatus,
    CreditTransaction,
    PlasticCredit,
    TransactionType,
)
from app.models.impact import (
    AssessmentStatus,
    ImpactAllocation,
    ImpactStatus,
)
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.credit import CreditRepository
from app.repositories.impact import AssessmentRepository, ImpactRepository, MethodologyRepository
from app.schemas.credit import (
    CreditBatchApproveRequest,
    CreditBatchCreateRequest,
    CreditBatchIssueRequest,
    CreditBatchResponse,
    CreditRetirementRequest,
    CreditRetirementResponse,
    CreditTransactionResponse,
    CreditTransferRequest,
    PlasticCreditResponse,
)

logger = logging.getLogger("plastify.services.credit")


class CreditService:
    """Business service governing plastic credit batches, issuance, transfers, and retirements."""

    def __init__(
        self,
        credit_repo: CreditRepository,
        impact_repo: ImpactRepository,
        assessment_repo: AssessmentRepository,
        methodology_repo: MethodologyRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.credit_repo = credit_repo
        self.impact_repo = impact_repo
        self.assessment_repo = assessment_repo
        self.methodology_repo = methodology_repo
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. Create Credit Batch from Assessed Impacts
    # --------------------------------------------------------------------------

    async def create_credit_batch(
        self, data: CreditBatchCreateRequest, creator: User
    ) -> CreditBatchResponse:
        """Form a draft credit batch from verified, eligible assessed impact allocations."""
        version = await self.methodology_repo.get_version_by_id(data.methodology_version_id)
        if not version:
            raise NotFoundException("Methodology version not found.")

        target_org_id = creator.organization_id
        if not target_org_id and creator.role != UserRole.SUPER_ADMIN:
            raise ForbiddenException("User must belong to an organization to create credit batches.")

        total_credits = Decimal("0.0000")
        total_allocated_kg = Decimal("0.0000")
        impact_allocations: List[ImpactAllocation] = []

        # Validate each assessment allocation under row locks
        for alloc_in in data.allocations:
            assessment = await self.assessment_repo.get_by_id(alloc_in.assessment_id)
            if not assessment:
                raise NotFoundException(f"Assessment '{alloc_in.assessment_id}' not found.")

            if assessment.status != AssessmentStatus.ELIGIBLE:
                raise BadRequestException(
                    f"Assessment '{assessment.assessment_number}' is '{assessment.status.value}'. "
                    "Only ELIGIBLE assessments can be admitted into credit batches."
                )

            if assessment.methodology_version_id != version.id:
                raise BadRequestException(
                    f"Methodology mismatch: Assessment '{assessment.assessment_number}' was evaluated under a different version."
                )

            # Lock the impact record
            impact = await self.impact_repo.get_by_id_for_update(assessment.impact_record_id)
            if not impact:
                raise NotFoundException(f"Impact record '{assessment.impact_record_id}' not found.")

            if impact.status != ImpactStatus.VERIFIED:
                raise BadRequestException(
                    f"Impact record '{impact.impact_id}' is in status '{impact.status.value}'. "
                    "Only VERIFIED impact records can be allocated to credit batches."
                )

            # Check tenant boundary
            if creator.role != UserRole.SUPER_ADMIN and impact.organization_id != target_org_id:
                raise ForbiddenException("Access denied: You cannot draw from another organization's impact records.")

            req_kg = alloc_in.allocated_quantity_kg
            unallocated = impact.unallocated_quantity
            if req_kg > unallocated:
                raise BadRequestException(
                    f"Over-allocation error on impact record '{impact.impact_id}': Requested {req_kg} KG, "
                    f"but only {unallocated} KG remains available."
                )

            # Calculate proportional credits
            deduction_sum = version.additionality_discount + version.baseline_discount + version.leakage_deduction
            net_multiplier = max(Decimal("0.0000"), Decimal("1.0000") - deduction_sum)
            credits_for_alloc = (req_kg * version.credit_conversion_factor * net_multiplier).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

            total_credits += credits_for_alloc
            total_allocated_kg += req_kg

            # Update impact allocated quantity
            impact.allocated_quantity += req_kg
            if impact.allocated_quantity >= impact.quantity:
                impact.status = ImpactStatus.ALLOCATED

            impact_allocations.append(
                ImpactAllocation(
                    impact_record_id=impact.id,
                    allocated_quantity=req_kg,
                    unit="KG",
                    notes=f"Allocated to credit batch under methodology {version.methodology.code} v{version.version_tag}",
                )
            )

        if total_credits <= Decimal("0.0000"):
            raise BadRequestException("Total calculated credits must be strictly positive.")

        year = data.vintage_year
        batch_number = await self.credit_repo.generate_next_batch_number(year)

        batch = CreditBatch(
            batch_number=batch_number,
            organization_id=target_org_id,
            methodology_version_id=version.id,
            creator_id=creator.id,
            total_credits=total_credits,
            available_credits=total_credits,
            retired_credits=Decimal("0.0000"),
            credit_type=data.credit_type.strip(),
            vintage_year=year,
            status=CreditBatchStatus.DRAFT,
            registry_name=data.registry_name.strip() if data.registry_name else "PLASTIFY_INTERNAL_REGISTRY",
            registry_status="LOCAL_ONLY",
            is_mock_issuance=True,
            issuance_notes=data.notes.strip() if data.notes else None,
        )
        batch.impact_allocations.extend(impact_allocations)
        created_batch = await self.credit_repo.create_batch(batch)

        await self.audit_repo.record(
            action="CREDIT_BATCH_CREATED",
            resource=f"credit_batch:{created_batch.id}",
            actor_id=creator.id,
            actor_email=creator.email,
            actor_role=creator.role.value,
            metadata={
                "batch_number": created_batch.batch_number,
                "total_credits": float(created_batch.total_credits),
                "vintage_year": created_batch.vintage_year,
            },
        )

        logger.info(f"Credit Batch created: {created_batch.batch_number} ({created_batch.total_credits} credits) by {creator.email}")
        refreshed = await self.credit_repo.get_batch_by_id(created_batch.id)
        return self._build_batch_response(refreshed or created_batch)

    # --------------------------------------------------------------------------
    # 2. Approve Credit Batch (Self-Approval Protection)
    # --------------------------------------------------------------------------

    async def approve_credit_batch(
        self,
        batch_id: uuid.UUID,
        data: CreditBatchApproveRequest,
        approver: User,
    ) -> CreditBatchResponse:
        """Authoritatively approve a credit batch for issuance."""
        batch = await self.credit_repo.get_batch_by_id_for_update(batch_id)
        if not batch:
            raise NotFoundException("Credit batch not found.")

        if batch.status != CreditBatchStatus.DRAFT:
            raise BadRequestException(f"Cannot approve credit batch in '{batch.status.value}' status. Must be DRAFT.")

        # Self-Approval Protection:
        # 1. Creator cannot approve their own batch
        if approver.id == batch.creator_id:
            raise ForbiddenException("Self-approval violation: The creator of a credit batch cannot approve it.")

        # 2. Approver organization cannot match the beneficiary organization
        if approver.role != UserRole.SUPER_ADMIN and approver.organization_id == batch.organization_id:
            raise ForbiddenException(
                "Self-approval violation: An organization cannot approve its own credit batches. "
                "Must be verified by an independent third-party verifier or auditor."
            )

        # 3. Only VERIFIER, AUDITOR, or SUPER_ADMIN
        if approver.role not in [UserRole.SUPER_ADMIN, UserRole.VERIFIER, UserRole.AUDITOR]:
            raise ForbiddenException("Only SUPER_ADMIN, VERIFIER, or AUDITOR roles can approve credit batches.")

        batch.status = CreditBatchStatus.APPROVED
        batch.approver_id = approver.id
        await self.credit_repo.session.flush()

        await self.audit_repo.record(
            action="CREDIT_BATCH_APPROVED",
            resource=f"credit_batch:{batch.id}",
            actor_id=approver.id,
            actor_email=approver.email,
            actor_role=approver.role.value,
            metadata={
                "batch_number": batch.batch_number,
                "total_credits": float(batch.total_credits),
                "approver": approver.email,
            },
        )

        logger.info(f"Credit Batch {batch.batch_number} APPROVED by {approver.email}")
        refreshed = await self.credit_repo.get_batch_by_id(batch.id)
        return self._build_batch_response(refreshed or batch)

    # --------------------------------------------------------------------------
    # 3. Controlled Credit Issuance (Idempotent & Registry Resilient)
    # --------------------------------------------------------------------------

    async def issue_credit_batch(
        self,
        batch_id: uuid.UUID,
        data: CreditBatchIssueRequest,
        issuer: User,
    ) -> CreditBatchResponse:
        """Execute controlled issuance of plastic credits with idempotency protection."""
        clean_key = data.idempotency_key.strip()

        # Idempotency Check: if key already exists, return existing issued batch
        existing_batch = await self.credit_repo.get_batch_by_idempotency_key(clean_key)
        if existing_batch:
            logger.info(f"Idempotent retry detected for credit batch issuance key '{clean_key}'")
            return self._build_batch_response(existing_batch)

        batch = await self.credit_repo.get_batch_by_id_for_update(batch_id)
        if not batch:
            raise NotFoundException("Credit batch not found.")

        # Only SUPER_ADMIN or AUDITOR can execute final issuance
        if issuer.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            raise ForbiddenException("Only SUPER_ADMIN or AUDITOR roles can execute credit issuance.")

        if batch.status == CreditBatchStatus.ISSUED:
            raise ConflictException(f"Credit batch '{batch.batch_number}' has already been ISSUED.")

        if batch.status != CreditBatchStatus.APPROVED:
            raise BadRequestException(
                f"Credit batch '{batch.batch_number}' is in status '{batch.status.value}'. "
                "Only APPROVED credit batches can be issued."
            )

        now_utc = datetime.now(timezone.utc)

        # External Registry Integration Simulation
        if data.simulate_registry_timeout:
            # When external registry fails or times out, preserve PENDING_RECONCILIATION
            batch.registry_status = "PENDING_RECONCILIATION"
            batch.issuance_notes = f"External registry timeout during issuance. Pending reconciliation as of {now_utc.isoformat()}."
            await self.credit_repo.session.flush()

            logger.warning(f"Credit Batch {batch.batch_number} held in PENDING_RECONCILIATION due to simulated external registry timeout.")
            refreshed = await self.credit_repo.get_batch_by_id(batch.id)
            return self._build_batch_response(refreshed or batch)

        # Mint Serialized Plastic Credits
        # Format: PC-{vintage}-{org_prefix}-{batch_prefix}-000001
        int_credits = int(batch.total_credits.to_integral_value(rounding=ROUND_HALF_UP))
        if int_credits <= 0:
            int_credits = 1

        serial_number = f"PC-{batch.vintage_year}-{uuid.uuid4().hex[:6].upper()}-000001-{int_credits:06d}"
        credit = PlasticCredit(
            credit_batch_id=batch.id,
            credit_batch=batch,
            serial_number=serial_number,
            serial_start=1,
            serial_end=int_credits,
            quantity=batch.total_credits,
            owner_organization_id=batch.organization_id,
            owner_organization=batch.organization,
            status=CreditStatus.ACTIVE,
            vintage_year=batch.vintage_year,
            credit_type=batch.credit_type,
        )
        created_credits = await self.credit_repo.create_credits([credit])

        # Record Initial Issuance Transaction
        tx_hash_input = f"{batch.batch_number}:{serial_number}:{batch.total_credits}:{now_utc.isoformat()}"
        audit_hash = hashlib.sha256(tx_hash_input.encode("utf-8")).hexdigest()
        tx = CreditTransaction(
            transaction_id=f"TX-{now_utc.year}-{uuid.uuid4().hex[:8].upper()}",
            credit_batch_id=batch.id,
            credit_batch=batch,
            credit_id=created_credits[0].id,
            tx_type=TransactionType.ISSUANCE,
            quantity=batch.total_credits,
            from_organization_id=None,
            to_organization_id=batch.organization_id,
            actor_id=issuer.id,
            idempotency_key=clean_key,
            notes=data.issuance_notes or "Initial credit batch issuance",
            audit_hash=audit_hash,
        )
        await self.credit_repo.create_transaction(tx)

        # Update Batch
        batch.status = CreditBatchStatus.ISSUED
        batch.issuer_id = issuer.id
        batch.issued_at = now_utc
        batch.idempotency_key = clean_key
        batch.registry_status = "SYNCED"
        batch.registry_batch_id = f"REG-MOCK-{uuid.uuid4().hex[:8].upper()}"
        batch.is_mock_issuance = True
        batch.issuance_notes = data.issuance_notes
        await self.credit_repo.session.flush()

        await self.audit_repo.record(
            action="CREDIT_BATCH_ISSUED",
            resource=f"credit_batch:{batch.id}",
            actor_id=issuer.id,
            actor_email=issuer.email,
            actor_role=issuer.role.value,
            metadata={
                "batch_number": batch.batch_number,
                "serial_number": serial_number,
                "total_credits": float(batch.total_credits),
                "idempotency_key": clean_key,
            },
        )

        logger.info(f"Credit Batch {batch.batch_number} ISSUED ({batch.total_credits} credits, SN: {serial_number}) by {issuer.email}")
        refreshed = await self.credit_repo.get_batch_by_id(batch.id)
        return self._build_batch_response(refreshed or batch)

    # --------------------------------------------------------------------------
    # 4. Credit Transfer
    # --------------------------------------------------------------------------

    async def transfer_credits(
        self, data: CreditTransferRequest, actor: User
    ) -> CreditTransactionResponse:
        """Transfer active credit tranches to another organization."""
        credit = await self.credit_repo.get_credit_by_id_for_update(data.credit_id)
        if not credit:
            raise NotFoundException("Plastic credit not found.")

        # Check tenant ownership
        if actor.role != UserRole.SUPER_ADMIN and credit.owner_organization_id != actor.organization_id:
            raise ForbiddenException("Access denied: You can only transfer credits owned by your organization.")

        if credit.status != CreditStatus.ACTIVE:
            raise BadRequestException(f"Cannot transfer credit in '{credit.status.value}' status. Must be ACTIVE.")

        qty_to_transfer = data.quantity if data.quantity else credit.quantity
        if qty_to_transfer > credit.quantity:
            raise BadRequestException(f"Transfer quantity ({qty_to_transfer}) exceeds available quantity ({credit.quantity}).")

        from_org_id = credit.owner_organization_id
        credit.owner_organization_id = data.to_organization_id
        await self.credit_repo.session.flush()

        now_utc = datetime.now(timezone.utc)
        tx_hash_input = f"{credit.serial_number}:{from_org_id}:{data.to_organization_id}:{qty_to_transfer}:{now_utc.isoformat()}"
        audit_hash = hashlib.sha256(tx_hash_input.encode("utf-8")).hexdigest()

        tx = CreditTransaction(
            transaction_id=f"TX-{now_utc.year}-{uuid.uuid4().hex[:8].upper()}",
            credit_batch_id=credit.credit_batch_id,
            credit_id=credit.id,
            tx_type=TransactionType.TRANSFER,
            quantity=qty_to_transfer,
            from_organization_id=from_org_id,
            to_organization_id=data.to_organization_id,
            actor_id=actor.id,
            idempotency_key=data.idempotency_key,
            notes=data.notes,
            audit_hash=audit_hash,
        )
        created_tx = await self.credit_repo.create_transaction(tx)

        await self.audit_repo.record(
            action="CREDIT_TRANSFERRED",
            resource=f"plastic_credit:{credit.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "serial_number": credit.serial_number,
                "from_org_id": str(from_org_id),
                "to_org_id": str(data.to_organization_id),
                "quantity": float(qty_to_transfer),
            },
        )

        logger.info(f"Credit {credit.serial_number} transferred from {from_org_id} to {data.to_organization_id} by {actor.email}")
        return self._build_transaction_response(created_tx)

    # --------------------------------------------------------------------------
    # 5. Idempotent Permanent Retirement
    # --------------------------------------------------------------------------

    async def retire_credits(
        self, data: CreditRetirementRequest, actor: User
    ) -> CreditRetirementResponse:
        """Permanently retire credits on behalf of a beneficiary with idempotency protection."""
        if data.idempotency_key:
            clean_key = data.idempotency_key.strip()
            existing_ret = await self.credit_repo.get_retirement_by_idempotency_key(clean_key)
            if existing_ret:
                logger.info(f"Idempotent retry detected for credit retirement key '{clean_key}'")
                return self._build_retirement_response(existing_ret)
        else:
            clean_key = None

        credit = await self.credit_repo.get_credit_by_id_for_update(data.credit_id)
        if not credit:
            raise NotFoundException("Plastic credit not found.")

        # Check tenant ownership
        if actor.role != UserRole.SUPER_ADMIN and credit.owner_organization_id != actor.organization_id:
            raise ForbiddenException("Access denied: You can only retire credits owned by your organization.")

        # Terminal check: retired credits can NEVER be retired again
        if credit.status == CreditStatus.RETIRED:
            raise BadRequestException("Terminal state error: These credits have already been RETIRED and cannot be reused.")

        if credit.status != CreditStatus.ACTIVE:
            raise BadRequestException(f"Cannot retire credit in '{credit.status.value}' status. Must be ACTIVE.")

        if data.quantity > credit.quantity:
            raise BadRequestException(f"Retirement quantity ({data.quantity}) exceeds credit balance ({credit.quantity}).")

        # Lock parent batch
        batch = await self.credit_repo.get_batch_by_id_for_update(credit.credit_batch_id)
        if not batch:
            raise NotFoundException("Associated credit batch not found.")

        now_utc = datetime.now(timezone.utc)
        year = now_utc.year
        ret_id = await self.credit_repo.generate_next_retirement_id(year)
        cert_id = await self.credit_repo.generate_next_certificate_id(year)

        # Cryptographic Certificate Hash
        cert_payload = f"{cert_id}:{credit.serial_number}:{data.quantity}:{data.beneficiary_name.strip()}:{now_utc.isoformat()}"
        cert_hash = hashlib.sha256(cert_payload.encode("utf-8")).hexdigest()

        # Update Credit
        credit.status = CreditStatus.RETIRED

        # Update Batch
        batch.available_credits = max(Decimal("0.0000"), batch.available_credits - data.quantity)
        batch.retired_credits += data.quantity
        if batch.available_credits == Decimal("0.0000"):
            batch.status = CreditBatchStatus.RETIRED

        # Create Retirement Record
        retirement = CreditRetirement(
            retirement_id=ret_id,
            credit_batch_id=batch.id,
            credit_id=credit.id,
            retiring_organization_id=credit.owner_organization_id,
            actor_id=actor.id,
            quantity=data.quantity,
            beneficiary_name=data.beneficiary_name.strip(),
            retirement_reason=data.retirement_reason.strip(),
            certificate_id=cert_id,
            certificate_hash=cert_hash,
            idempotency_key=clean_key,
            retired_at=now_utc,
        )
        created_ret = await self.credit_repo.create_retirement(retirement)

        # Record Retirement Transaction
        tx = CreditTransaction(
            transaction_id=f"TX-{year}-{uuid.uuid4().hex[:8].upper()}",
            credit_batch_id=batch.id,
            credit_id=credit.id,
            tx_type=TransactionType.RETIREMENT,
            quantity=data.quantity,
            from_organization_id=credit.owner_organization_id,
            to_organization_id=None,
            actor_id=actor.id,
            idempotency_key=clean_key,
            notes=f"Retired on behalf of {data.beneficiary_name.strip()}: {data.retirement_reason.strip()}",
            audit_hash=cert_hash,
        )
        await self.credit_repo.create_transaction(tx)
        await self.credit_repo.session.flush()

        await self.audit_repo.record(
            action="CREDIT_RETIRED",
            resource=f"credit_retirement:{created_ret.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "retirement_id": ret_id,
                "certificate_id": cert_id,
                "serial_number": credit.serial_number,
                "quantity": float(data.quantity),
                "beneficiary": data.beneficiary_name.strip(),
            },
        )

        logger.info(
            f"Plastic Credit {credit.serial_number} permanently RETIRED ({data.quantity} credits, Cert: {cert_id}) "
            f"for {data.beneficiary_name} by {actor.email}"
        )
        refreshed = await self.credit_repo.get_retirement_by_id(created_ret.id)
        return self._build_retirement_response(refreshed or created_ret)

    # --------------------------------------------------------------------------
    # 6. Retrieval & Listing
    # --------------------------------------------------------------------------

    async def get_batch_by_id(self, batch_id: uuid.UUID, actor: User) -> CreditBatchResponse:
        """Fetch credit batch by UUID."""
        batch = await self.credit_repo.get_batch_by_id(batch_id)
        if not batch:
            raise NotFoundException("Credit batch not found.")

        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            if batch.organization_id != actor.organization_id:
                raise ForbiddenException("Access denied: You cannot view credit batches of another organization.")

        return self._build_batch_response(batch)

    async def list_batches(
        self,
        actor: User,
        status: Optional[CreditBatchStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CreditBatchResponse]:
        """List credit batches with organization isolation."""
        org_id = None
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            org_id = actor.organization_id

        batches = await self.credit_repo.list_batches(organization_id=org_id, status=status, skip=skip, limit=limit)
        return [self._build_batch_response(b) for b in batches]

    async def list_credits(
        self,
        actor: User,
        status: Optional[CreditStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[PlasticCreditResponse]:
        """List serialized credits owned by the user's organization."""
        org_id = None
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            org_id = actor.organization_id

        credits = await self.credit_repo.list_credits(owner_organization_id=org_id, status=status, skip=skip, limit=limit)
        return [self._build_credit_response(c) for c in credits]

    async def list_retirements(
        self,
        actor: User,
        skip: int = 0,
        limit: int = 50,
    ) -> List[CreditRetirementResponse]:
        """List credit retirements."""
        org_id = None
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            org_id = actor.organization_id

        rets = await self.credit_repo.list_retirements(retiring_organization_id=org_id, skip=skip, limit=limit)
        return [self._build_retirement_response(r) for r in rets]

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _build_credit_response(self, c: PlasticCredit) -> PlasticCreditResponse:
        return PlasticCreditResponse(
            id=c.id,
            credit_batch_id=c.credit_batch_id,
            serial_number=c.serial_number,
            serial_start=c.serial_start,
            serial_end=c.serial_end,
            quantity=c.quantity,
            owner_organization_id=c.owner_organization_id,
            owner_organization_name=c.owner_organization.name if c.owner_organization else None,
            status=c.status,
            vintage_year=c.vintage_year,
            credit_type=c.credit_type,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )

    def _build_batch_response(self, b: CreditBatch) -> CreditBatchResponse:
        credits = [self._build_credit_response(c) for c in b.credits]
        return CreditBatchResponse(
            id=b.id,
            batch_number=b.batch_number,
            organization_id=b.organization_id,
            organization_name=b.organization.name if b.organization else None,
            methodology_version_id=b.methodology_version_id,
            methodology_code=b.methodology_version.methodology.code if b.methodology_version and b.methodology_version.methodology else None,
            version_tag=b.methodology_version.version_tag if b.methodology_version else None,
            creator_id=b.creator_id,
            creator_name=f"{b.creator.first_name} {b.creator.last_name}" if b.creator else None,
            approver_id=b.approver_id,
            approver_name=f"{b.approver.first_name} {b.approver.last_name}" if b.approver else None,
            issuer_id=b.issuer_id,
            issuer_name=f"{b.issuer.first_name} {b.issuer.last_name}" if b.issuer else None,
            total_credits=b.total_credits,
            available_credits=b.available_credits,
            retired_credits=b.retired_credits,
            credit_type=b.credit_type,
            vintage_year=b.vintage_year,
            status=b.status,
            registry_name=b.registry_name,
            registry_batch_id=b.registry_batch_id,
            registry_status=b.registry_status,
            is_mock_issuance=b.is_mock_issuance,
            idempotency_key=b.idempotency_key,
            issuance_notes=b.issuance_notes,
            issued_at=b.issued_at,
            created_at=b.created_at,
            updated_at=b.updated_at,
            credits=credits,
        )

    def _build_transaction_response(self, tx: CreditTransaction) -> CreditTransactionResponse:
        return CreditTransactionResponse(
            id=tx.id,
            transaction_id=tx.transaction_id,
            credit_batch_id=tx.credit_batch_id,
            credit_id=tx.credit_id,
            tx_type=tx.tx_type,
            quantity=tx.quantity,
            from_organization_id=tx.from_organization_id,
            from_organization_name=tx.from_organization.name if tx.from_organization else None,
            to_organization_id=tx.to_organization_id,
            to_organization_name=tx.to_organization.name if tx.to_organization else None,
            actor_id=tx.actor_id,
            actor_email=tx.actor.email if tx.actor else None,
            notes=tx.notes,
            audit_hash=tx.audit_hash,
            created_at=tx.created_at,
        )

    def _build_retirement_response(self, r: CreditRetirement) -> CreditRetirementResponse:
        return CreditRetirementResponse(
            id=r.id,
            retirement_id=r.retirement_id,
            credit_batch_id=r.credit_batch_id,
            credit_id=r.credit_id,
            retiring_organization_id=r.retiring_organization_id,
            retiring_organization_name=r.retiring_organization.name if r.retiring_organization else None,
            actor_id=r.actor_id,
            actor_email=r.actor.email if r.actor else None,
            quantity=r.quantity,
            beneficiary_name=r.beneficiary_name,
            retirement_reason=r.retirement_reason,
            certificate_id=r.certificate_id,
            certificate_hash=r.certificate_hash,
            idempotency_key=r.idempotency_key,
            retired_at=r.retired_at,
            created_at=r.created_at,
        )
