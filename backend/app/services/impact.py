"""PLASTIFY Impact Ledger Service.

Manages authoritative physical outcome records, provenance anchors, evidence manifests,
and traceable audit corrections.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.circular import MaterialBatchStatus, UpcyclingBatchStatus
from app.models.impact import ImpactOutcomeType, ImpactRecord, ImpactStatus
from app.models.recovery import RecoveryStatus
from app.models.user import User, UserRole
from app.models.verification import VerificationDecision
from app.repositories.audit import AuditRepository
from app.repositories.circular import CircularRepository
from app.repositories.impact import ImpactRepository
from app.repositories.recovery import RecoveryRepository
from app.repositories.verification import VerificationRepository
from app.schemas.impact import (
    ImpactAllocationResponse,
    ImpactRecordCreateRequest,
    ImpactRecordResponse,
    ImpactRecordSupersedeRequest,
)

logger = logging.getLogger("plastify.services.impact")


class ImpactService:
    """Business service governing the PLASTIFY Impact Ledger."""

    def __init__(
        self,
        impact_repo: ImpactRepository,
        recovery_repo: RecoveryRepository,
        circular_repo: CircularRepository,
        verification_repo: VerificationRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.impact_repo = impact_repo
        self.recovery_repo = recovery_repo
        self.circular_repo = circular_repo
        self.verification_repo = verification_repo
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. Register Verified Physical Impact
    # --------------------------------------------------------------------------

    async def register_impact_from_source(
        self, data: ImpactRecordCreateRequest, actor: User
    ) -> ImpactRecordResponse:
        """Register an authoritative physical impact record anchored to a verified source event."""
        year = datetime.now(timezone.utc).year

        # 1. COLLECTION Outcome
        if data.outcome_type == ImpactOutcomeType.COLLECTION:
            if not data.source_recovery_id:
                raise BadRequestException("Source recovery_id is required for COLLECTION impact records.")

            rec = await self.recovery_repo.get_with_details(data.source_recovery_id)
            if not rec:
                raise NotFoundException(f"Recovery event '{data.source_recovery_id}' not found.")

            if rec.status != RecoveryStatus.VERIFIED:
                raise BadRequestException(
                    f"Recovery event '{rec.recovery_id}' is in status '{rec.status.value}'. "
                    "Only officially VERIFIED recoveries can be admitted to the Impact Ledger."
                )

            # Check tenant boundary
            if actor.role != UserRole.SUPER_ADMIN and rec.collector_organization_id != actor.organization_id:
                raise ForbiddenException("Access denied: You can only register impact for your own organization.")

            # Duplicate claim check
            existing = await self.impact_repo.get_by_source_recovery_id(rec.id)
            if existing:
                raise ConflictException(
                    f"Duplicate claim prevented: Recovery '{rec.recovery_id}' has already been registered "
                    f"in the Impact Ledger under '{existing.impact_id}'."
                )

            # Latest verification record
            ver_rec = None
            if rec.verification_records:
                for v in rec.verification_records:
                    if v.decision == VerificationDecision.APPROVED:
                        ver_rec = v
                        break
            if not ver_rec:
                ver_list = await self.verification_repo.list_records_by_recovery(rec.id)
                for v in ver_list:
                    if v.decision == VerificationDecision.APPROVED:
                        ver_rec = v
                        break

            # Build evidence manifest
            manifest = [
                {
                    "evidence_id": str(e.id),
                    "evidence_type": e.type.value if hasattr(e.type, "value") else str(e.type),
                    "sha256": e.sha256_hash,
                    "filename": e.original_filename,
                }
                for e in rec.evidence
            ]

            impact_id = await self.impact_repo.generate_next_impact_id(ImpactOutcomeType.COLLECTION, year)
            final_weight = Decimal(str(ver_rec.verified_weight_kg if ver_rec and ver_rec.verified_weight_kg else rec.weight_kg))

            record = ImpactRecord(
                impact_id=impact_id,
                outcome_type=ImpactOutcomeType.COLLECTION,
                status=ImpactStatus.VERIFIED,
                source_recovery_id=rec.id,
                verification_record_id=ver_rec.id if ver_rec else None,
                organization_id=rec.collector_organization_id,
                program_id=rec.program_id,
                material_type=rec.material_type,
                quantity=final_weight,
                allocated_quantity=Decimal("0.0000"),
                unit="KG",
                location_name=rec.collection_location,
                coordinates=rec.collection_coordinates,
                recorded_at=rec.collected_at,
                evidence_manifest=manifest,
                metadata_json=data.metadata or {},
            )
            created = await self.impact_repo.create(record)

        # 2. RECYCLED_OUTPUT Outcome
        elif data.outcome_type in [ImpactOutcomeType.RECYCLING_INPUT, ImpactOutcomeType.RECYCLED_OUTPUT]:
            if not data.source_material_batch_id:
                raise BadRequestException(f"Source material_batch_id is required for '{data.outcome_type.value}' impact records.")

            batch = await self.circular_repo.get_material_batch_by_id(data.source_material_batch_id)
            if not batch:
                raise NotFoundException(f"Material batch '{data.source_material_batch_id}' not found.")

            if batch.status != MaterialBatchStatus.COMPLETED:
                raise BadRequestException(
                    f"Material batch '{batch.batch_id}' is not COMPLETED. "
                    "Only certified completed recycling batches can generate impact records."
                )

            # Check tenant boundary
            if actor.role != UserRole.SUPER_ADMIN and batch.recycler_organization_id != actor.organization_id:
                raise ForbiddenException("Access denied: You can only register impact for your own recycling operations.")

            # Duplicate claim check
            existing = await self.impact_repo.get_by_source_material_batch_id(batch.id)
            if existing and existing.outcome_type == data.outcome_type:
                raise ConflictException(
                    f"Duplicate claim prevented: Material batch '{batch.batch_id}' has already been registered "
                    f"in the Impact Ledger under '{existing.impact_id}'."
                )

            qty = Decimal(str(batch.recycled_output_kg if data.outcome_type == ImpactOutcomeType.RECYCLED_OUTPUT else batch.input_weight_kg))
            if qty <= 0:
                raise BadRequestException(f"Cannot register impact record with zero quantity ({qty} KG).")

            manifest = [
                {
                    "evidence_id": str(e.id),
                    "evidence_type": e.evidence_type,
                    "sha256": e.sha256_hash,
                    "filename": e.original_filename,
                }
                for e in batch.evidences
            ]

            impact_id = await self.impact_repo.generate_next_impact_id(data.outcome_type, year)
            record = ImpactRecord(
                impact_id=impact_id,
                outcome_type=data.outcome_type,
                status=ImpactStatus.VERIFIED,
                source_material_batch_id=batch.id,
                organization_id=batch.recycler_organization_id,
                material_type=batch.material_type,
                quantity=qty,
                allocated_quantity=Decimal("0.0000"),
                unit="KG",
                location_name="Recycling Facility",
                recorded_at=batch.processing_date,
                evidence_manifest=manifest,
                metadata_json=data.metadata or {},
            )
            created = await self.impact_repo.create(record)

        else:
            raise BadRequestException(f"Unsupported automated impact outcome registration type: '{data.outcome_type.value}'")

        await self.audit_repo.record(
            action="IMPACT_RECORD_REGISTERED",
            resource=f"impact_record:{created.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "impact_id": created.impact_id,
                "outcome_type": created.outcome_type.value,
                "quantity": float(created.quantity),
                "material_type": created.material_type,
            },
        )

        logger.info(f"Impact Record registered: {created.impact_id} ({created.quantity} KG {created.material_type}) by {actor.email}")
        refreshed = await self.impact_repo.get_by_id(created.id)
        return self._build_impact_response(refreshed or created)

    # --------------------------------------------------------------------------
    # 2. Supersede / Audit Correction
    # --------------------------------------------------------------------------

    async def supersede_impact_record(
        self,
        impact_id: uuid.UUID,
        data: ImpactRecordSupersedeRequest,
        actor: User,
    ) -> ImpactRecordResponse:
        """Traceably supersede an existing impact record with an audit correction."""
        original = await self.impact_repo.get_by_id_for_update(impact_id)
        if not original:
            raise NotFoundException("Impact record not found.")

        # Only Super Admin or Auditor can supersede
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            raise ForbiddenException("Only SUPER_ADMIN or AUDITOR roles can supersede verified impact records.")

        if original.status in [ImpactStatus.SUPERSEDED, ImpactStatus.REVOKED]:
            raise BadRequestException(f"Impact record is already in '{original.status.value}' status.")

        # Check if already allocated to credit batches
        if original.allocated_quantity > data.new_quantity_kg:
            raise BadRequestException(
                f"Cannot adjust quantity to {data.new_quantity_kg} KG: "
                f"{original.allocated_quantity} KG has already been committed to downstream credit batches."
            )

        year = datetime.now(timezone.utc).year
        new_code = await self.impact_repo.generate_next_impact_id(original.outcome_type, year)

        # Create amended replacement record
        replacement = ImpactRecord(
            impact_id=new_code,
            outcome_type=original.outcome_type,
            status=ImpactStatus.VERIFIED,
            source_recovery_id=original.source_recovery_id,
            source_material_batch_id=original.source_material_batch_id,
            source_upcycling_batch_id=original.source_upcycling_batch_id,
            verification_record_id=original.verification_record_id,
            organization_id=original.organization_id,
            program_id=original.program_id,
            material_type=original.material_type,
            quantity=data.new_quantity_kg,
            allocated_quantity=original.allocated_quantity,
            unit=original.unit,
            location_name=original.location_name,
            coordinates=original.coordinates,
            recorded_at=original.recorded_at,
            evidence_manifest=original.evidence_manifest,
            supersedes_id=original.id,
            metadata_json={
                **(data.metadata or {}),
                "audit_correction_reason": data.reason,
                "original_impact_id": original.impact_id,
                "original_quantity_kg": float(original.quantity),
            },
        )
        created_replacement = await self.impact_repo.create(replacement)

        # Update original record
        original.status = ImpactStatus.SUPERSEDED
        original.superseded_by_id = created_replacement.id
        await self.impact_repo.session.flush()

        await self.audit_repo.record(
            action="IMPACT_RECORD_SUPERSEDED",
            resource=f"impact_record:{original.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "original_impact_id": original.impact_id,
                "replacement_impact_id": created_replacement.impact_id,
                "old_quantity": float(original.quantity),
                "new_quantity": float(data.new_quantity_kg),
                "reason": data.reason,
            },
        )

        logger.info(f"Impact record '{original.impact_id}' superseded by '{created_replacement.impact_id}' ({data.new_quantity_kg} KG)")
        refreshed = await self.impact_repo.get_by_id(created_replacement.id)
        return self._build_impact_response(refreshed or created_replacement)

    # --------------------------------------------------------------------------
    # 3. Retrieval & Listing
    # --------------------------------------------------------------------------

    async def get_impact_by_id(self, impact_id: uuid.UUID, actor: User) -> ImpactRecordResponse:
        """Fetch impact record with tenant access authorization."""
        record = await self.impact_repo.get_by_id(impact_id)
        if not record:
            raise NotFoundException("Impact record not found.")

        self._assert_impact_access(record, actor)
        return self._build_impact_response(record)

    async def list_impact_records(
        self,
        actor: User,
        outcome_type: Optional[ImpactOutcomeType] = None,
        status: Optional[ImpactStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[ImpactRecordResponse]:
        """List impact records scoped to actor's organization unless Super Admin / Auditor."""
        org_id = None
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            org_id = actor.organization_id

        records = await self.impact_repo.list_impacts(
            organization_id=org_id,
            outcome_type=outcome_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return [self._build_impact_response(r) for r in records]

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _assert_impact_access(self, record: ImpactRecord, actor: User) -> None:
        """Assert that actor belongs to the impact record's organization or holds auditor privileges."""
        if actor.role in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            return
        if record.organization_id != actor.organization_id:
            raise ForbiddenException("Access denied: You do not have permission to view this impact record.")

    def _build_impact_response(self, record: ImpactRecord) -> ImpactRecordResponse:
        """Serialize an ImpactRecord ORM model to its API response schema."""
        allocations = [
            ImpactAllocationResponse(
                id=a.id,
                impact_record_id=a.impact_record_id,
                credit_batch_id=a.credit_batch_id,
                allocated_quantity=a.allocated_quantity,
                unit=a.unit,
                notes=a.notes,
                created_at=a.created_at,
            )
            for a in record.allocations
        ]
        return ImpactRecordResponse(
            id=record.id,
            impact_id=record.impact_id,
            outcome_type=record.outcome_type,
            status=record.status,
            source_recovery_id=record.source_recovery_id,
            source_material_batch_id=record.source_material_batch_id,
            source_upcycling_batch_id=record.source_upcycling_batch_id,
            verification_record_id=record.verification_record_id,
            organization_id=record.organization_id,
            organization_name=record.organization.name if record.organization else None,
            program_id=record.program_id,
            program_name=record.program.name if record.program else None,
            material_type=record.material_type,
            quantity=record.quantity,
            allocated_quantity=record.allocated_quantity,
            unallocated_quantity=record.unallocated_quantity,
            unit=record.unit,
            location_name=record.location_name,
            coordinates=record.coordinates,
            recorded_at=record.recorded_at,
            evidence_manifest=record.evidence_manifest,
            superseded_by_id=record.superseded_by_id,
            supersedes_id=record.supersedes_id,
            metadata_json=record.metadata_json,
            created_at=record.created_at,
            updated_at=record.updated_at,
            allocations=allocations,
        )
