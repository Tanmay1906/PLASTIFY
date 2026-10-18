"""PLASTIFY Verification Engine Service.

Domain service governing human verification reviews, evidence dossiers,
atomic approvals, rejections, and Sentinel/audit findings.
"""

from datetime import datetime, timezone
from typing import List, Optional
import uuid

from app.core.config import Settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.custody import CustodyState
from app.models.logistics import DeliveryStatus
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.user import User, UserRole
from app.models.verification import (
    FindingCategory,
    FindingSeverity,
    VerificationDecision,
    VerificationFinding,
    VerificationRecord,
)
from app.repositories.audit import AuditRepository
from app.repositories.evidence import EvidenceRepository
from app.repositories.logistics import LogisticsRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.repositories.recovery import RecoveryHistoryRepository, RecoveryRepository
from app.repositories.verification import VerificationRepository
from app.schemas.custody import CustodyTransitionRequest
from app.schemas.evidence import EvidenceResponse
from app.schemas.logistics import (
    DeliveryEvidenceResponse,
    DeliveryResponse,
    LogisticsAssignmentResponse,
)
from app.schemas.recovery import RecoveryResponse
from app.schemas.verification import (
    ApproveVerificationRequest,
    FlagVerificationRequest,
    RejectVerificationRequest,
    VerificationFindingCreateRequest,
    VerificationFindingResolveRequest,
    VerificationFindingResponse,
    VerificationPackageResponse,
    VerificationQueueItemResponse,
    VerificationRecordResponse,
    WeightComparisonSummary,
)
from app.services.base import BaseService
from app.services.custody import ChainOfCustodyService


class VerificationService(BaseService):
    """Authoritative domain service executing human verification determination workflows."""

    def __init__(
        self,
        settings: Settings,
        verification_repo: VerificationRepository,
        recovery_repo: RecoveryRepository,
        history_repo: RecoveryHistoryRepository,
        logistics_repo: LogisticsRepository,
        evidence_repo: EvidenceRepository,
        organization_repo: OrganizationRepository,
        program_repo: ProgramRepository,
        program_partner_repo: ProgramPartnerRepository,
        custody_service: ChainOfCustodyService,
        audit_repo: AuditRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.verification_repo = verification_repo
        self.recovery_repo = recovery_repo
        self.history_repo = history_repo
        self.logistics_repo = logistics_repo
        self.evidence_repo = evidence_repo
        self.organization_repo = organization_repo
        self.program_repo = program_repo
        self.program_partner_repo = program_partner_repo
        self.custody_service = custody_service
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. Verification Queue
    # --------------------------------------------------------------------------

    async def get_verification_queue(
        self,
        requester: User,
        material_type: Optional[str] = None,
        status: Optional[RecoveryStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[VerificationQueueItemResponse]:
        """Fetch recovery events requiring human verification review."""
        if requester.role not in [UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only Verifiers, Auditors, or Admins can access the queue.")

        # Determine program jurisdiction
        program_ids: Optional[List[uuid.UUID]] = None
        if requester.role != UserRole.SUPER_ADMIN:
            if not requester.organization_id:
                return []
            partner_programs = await self.program_partner_repo.list_by_partner_org(
                requester.organization_id
            )
            program_ids = [p.program_id for p in partner_programs]
            if not program_ids:
                return []

        recoveries = await self.verification_repo.list_verification_queue(
            program_ids=program_ids,
            material_type=material_type,
            status=status,
            skip=skip,
            limit=limit,
        )

        queue_items: List[VerificationQueueItemResponse] = []
        for r in recoveries:
            # Check delivery details
            delivery = await self.logistics_repo.get_delivery_by_recovery_id(r.id)
            unresolved_critical = await self.verification_repo.count_unresolved_critical_findings(r.id)
            all_findings = await self.verification_repo.list_findings_by_recovery(r.id)

            queue_items.append(
                VerificationQueueItemResponse(
                    recovery_id=r.id,
                    recovery_human_id=r.recovery_id,
                    program_id=r.program_id,
                    program_name=r.program.name if r.program else "Unknown Program",
                    collector_organization_id=r.collector_organization_id,
                    collector_organization_name=r.collector_organization.name
                    if r.collector_organization
                    else "Unknown Collector",
                    recycler_organization_id=delivery.recycler_organization_id if delivery else None,
                    recycler_organization_name=delivery.recycler_organization.name
                    if delivery and delivery.recycler_organization
                    else None,
                    material_type=r.material_type,
                    weight_kg=r.weight_kg,
                    collected_at=r.collected_at,
                    collection_location=r.collection_location,
                    custody_status=r.custody_status,
                    recovery_status=r.status,
                    weight_tolerance_status=delivery.weight_tolerance_status.value
                    if delivery
                    else None,
                    has_critical_findings=unresolved_critical > 0,
                    findings_count=len(all_findings),
                    queued_at=r.created_at,
                )
            )

        return queue_items

    # --------------------------------------------------------------------------
    # 2. Comprehensive Verification Package
    # --------------------------------------------------------------------------

    async def get_verification_package(
        self, recovery_id: uuid.UUID, requester: User
    ) -> VerificationPackageResponse:
        """Inspect the entire verification dossier for a recovery event."""
        recovery = await self.recovery_repo.get_with_details(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' was not found.")

        # Access control
        await self._assert_can_view_verification_package(recovery, requester)

        # 1. Collection Evidence
        evidence_records = await self.evidence_repo.list_by_recovery(recovery.id)
        evidence_responses = [
            EvidenceResponse(
                id=e.id,
                recovery_id=e.recovery_id,
                recovery_human_id=recovery.recovery_id,
                uploader_id=e.uploader_id,
                uploader_name=e.uploader.full_name if e.uploader else None,
                type=e.type,
                storage_key=e.storage_key,
                original_filename=e.original_filename,
                mime_type=e.mime_type,
                size=e.size,
                sha256_hash=e.sha256_hash,
                scan_status=e.scan_status,
                notes=e.notes,
                created_at=e.created_at,
            )
            for e in evidence_records
        ]

        # 2. Logistics & Delivery
        assignment = await self.logistics_repo.get_assignment_by_recovery_id(recovery.id)
        delivery = await self.logistics_repo.get_delivery_by_recovery_id(recovery.id)

        assignment_resp: Optional[LogisticsAssignmentResponse] = None
        if assignment:
            assignment_resp = self._build_assignment_response(assignment)

        delivery_resp: Optional[DeliveryResponse] = None
        delivery_evidence_resp: List[DeliveryEvidenceResponse] = []
        if delivery:
            delivery_resp = self._build_delivery_response(delivery)
            delivery_evidence_resp = delivery_resp.evidence_records

        # 3. Weight Comparison Summary
        baseline_weight = delivery.expected_weight_kg if delivery else recovery.weight_kg
        received_weight = delivery.received_weight_kg if delivery else None
        delivered_weight = delivery.delivered_weight_kg if delivery else None
        discrepancy_kg = delivery.weight_discrepancy_kg if delivery else None
        discrepancy_pct: Optional[float] = None
        if discrepancy_kg is not None and baseline_weight > 0:
            discrepancy_pct = round((discrepancy_kg / baseline_weight) * 100.0, 2)

        weight_summary = WeightComparisonSummary(
            expected_weight_kg=baseline_weight,
            delivered_weight_kg=delivered_weight,
            received_weight_kg=received_weight,
            discrepancy_kg=discrepancy_kg,
            discrepancy_pct=discrepancy_pct,
            tolerance_pct=delivery.weight_tolerance_pct if delivery else 2.0,
            tolerance_status=delivery.weight_tolerance_status.value if delivery else None,
        )

        # 4. Chain of Custody Timeline
        timeline = await self.custody_service.get_custody_timeline(recovery.id, requester)

        # 5. Sentinel & Verification Findings
        findings = await self.verification_repo.list_findings_by_recovery(recovery.id)
        findings_resp = [self._build_finding_response(f) for f in findings]

        sentinel_result_resp = None
        sent_res = getattr(recovery, "sentinel_result", None)
        if not sent_res:
            from app.repositories.sentinel import SentinelRepository

            sent_repo = SentinelRepository(self.verification_repo.session)
            sent_res = await sent_repo.get_by_recovery_id(recovery.id)

        if sent_res:
            from app.schemas.sentinel import SentinelFlagResponse, SentinelResultResponse

            flags_resp = [
                SentinelFlagResponse(
                    id=fl.id,
                    result_id=fl.result_id,
                    detector=fl.detector,
                    severity=fl.severity,
                    reason=fl.reason,
                    confidence=fl.confidence,
                    evidence_reference=fl.evidence_reference,
                    metadata=fl.metadata_json,
                    created_at=fl.created_at,
                )
                for fl in (sent_res.flags or [])
            ]
            sentinel_result_resp = SentinelResultResponse(
                id=sent_res.id,
                recovery_id=sent_res.recovery_id,
                recovery_human_id=recovery.recovery_id,
                risk_score=sent_res.risk_score,
                risk_level=sent_res.risk_level,
                summary=sent_res.summary,
                flags_count=sent_res.flags_count,
                critical_count=sent_res.critical_count,
                high_count=sent_res.high_count,
                medium_count=sent_res.medium_count,
                low_count=sent_res.low_count,
                status=sent_res.status,
                flags=flags_resp,
                metadata=sent_res.metadata_json,
                created_at=sent_res.created_at,
                updated_at=sent_res.updated_at,
            )

        # 6. Prior Verification Records
        records = await self.verification_repo.list_records_by_recovery(recovery.id)
        records_resp = [self._build_record_response(r) for r in records]

        recovery_resp = await self._build_recovery_response(recovery)

        return VerificationPackageResponse(
            recovery=recovery_resp,
            collection_evidence=evidence_responses,
            logistics_assignment=assignment_resp,
            delivery=delivery_resp,
            delivery_evidence=delivery_evidence_resp,
            weight_comparison=weight_summary,
            custody_timeline=timeline.events,
            sentinel_findings=findings_resp,
            sentinel_result=sentinel_result_resp,
            existing_records=records_resp,
        )

    # --------------------------------------------------------------------------
    # 3. Action: APPROVE
    # --------------------------------------------------------------------------

    async def approve_recovery(
        self,
        recovery_id: uuid.UUID,
        data: ApproveVerificationRequest,
        requester: User,
    ) -> VerificationRecordResponse:
        """Grant authoritative human verification approval with atomic lock & server-side checks."""
        # Check 1: Verifier authorized
        if requester.role not in [UserRole.VERIFIER, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only certified Verifiers or Super Admins can verify recovery events.")

        # Atomic lock on the RecoveryEvent row
        recovery = await self.verification_repo.get_recovery_for_update(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' was not found.")

        # Check 2: Verifier cannot belong to an unauthorized organization
        await self._assert_verifier_organization_authorized(recovery, requester)

        # Check 3: Verifier cannot approve their own collection
        if recovery.collector_id == requester.id:
            raise BadRequestException("Self-verification is strictly prohibited: Verifiers cannot approve their own collection events.")
        if requester.organization_id and requester.organization_id == recovery.collector_organization_id:
            raise BadRequestException("Conflict of interest: Verifiers cannot approve collections created by their own organization.")

        # Check 4: Recovery state validity & duplicate verification prevention
        if recovery.status == RecoveryStatus.VERIFIED:
            raise BadRequestException("Duplicate verification: Recovery event is already VERIFIED.")
        if recovery.status == RecoveryStatus.REJECTED:
            raise BadRequestException("Cannot verify a REJECTED recovery event.")
        if recovery.status in [RecoveryStatus.DRAFT, RecoveryStatus.CANCELLED]:
            raise BadRequestException(f"Cannot verify recovery event in '{recovery.status.value}' status.")

        # Check 5: Custody state validity (Must reach RECEIVED)
        current_custody = recovery.custody_status or CustodyState.CREATED.value
        if current_custody != CustodyState.RECEIVED.value:
            raise BadRequestException(
                f"Invalid custody state '{current_custody}'. Material batch must reach 'RECEIVED' status before verification approval."
            )

        # Check 6: Required collection evidence exists
        evidence_records = await self.evidence_repo.list_by_recovery(recovery.id)
        if not evidence_records:
            raise BadRequestException("Verification rejected: Required collection evidence photos/documents are missing.")

        # Check 7: Delivery exists and is confirmed received
        delivery = await self.logistics_repo.get_delivery_by_recovery_id(recovery.id)
        if not delivery or delivery.status != DeliveryStatus.RECEIVED:
            raise BadRequestException(
                "Verification rejected: Delivery record is missing or has not been confirmed received by the destination facility."
            )

        # Check 8: No critical unresolved blocking issues
        unresolved_critical = await self.verification_repo.count_unresolved_critical_findings(recovery.id)
        if unresolved_critical > 0:
            raise BadRequestException(
                f"Cannot approve recovery: {unresolved_critical} unresolved critical blocking issue(s) exist."
            )

        # Determine approved weight
        verified_weight = (
            data.verified_weight_kg
            or delivery.received_weight_kg
            or delivery.delivered_weight_kg
            or recovery.weight_kg
        )

        # Generate unique verification code
        verification_code = f"VRF-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"

        # Resolve organization id for record
        org_id = requester.organization_id or recovery.program.organization_id

        # 1. Create immutable VerificationRecord
        record = VerificationRecord(
            verification_code=verification_code,
            recovery_id=recovery.id,
            verifier_id=requester.id,
            verifier_organization_id=org_id,
            decision=VerificationDecision.APPROVED,
            verified_weight_kg=verified_weight,
            reason=None,
            notes=data.notes,
            checklist=data.checklist or {},
        )
        created_record = await self.verification_repo.create_record(record)

        # 2. Advance Chain of Custody to VERIFIED
        await self.custody_service.transition_custody(
            recovery.id,
            CustodyTransitionRequest(
                new_state=CustodyState.VERIFIED,
                notes=data.notes or f"Official human verification approved ({verification_code})",
                metadata={
                    "verification_code": verification_code,
                    "verified_weight_kg": verified_weight,
                    "verifier_email": requester.email,
                },
            ),
            requester,
        )

        # 3. Transition RecoveryEvent to VERIFIED
        from_status = recovery.status.value
        recovery.status = RecoveryStatus.VERIFIED

        await self.verification_repo.session.flush()

        # 4. Record state history & audit log
        await self.history_repo.record_transition(
            recovery_event_id=recovery.id,
            from_status=from_status,
            to_status=RecoveryStatus.VERIFIED.value,
            actor_id=requester.id,
            actor_role=requester.role.value,
            notes=data.notes or "Verification approved",
            event_metadata={
                "verification_code": verification_code,
                "verified_weight_kg": verified_weight,
            },
        )

        await self.audit_repo.record(
            action="RECOVERY_VERIFIED",
            resource=f"recovery:{recovery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "verification_code": verification_code,
                "verified_weight_kg": verified_weight,
                "decision": VerificationDecision.APPROVED.value,
            },
        )

        self.logger.info(
            f"Recovery Event {recovery.recovery_id} VERIFIED by {requester.email} ({verification_code})"
        )

        refreshed = await self.verification_repo.get_record_by_id(created_record.id)
        return self._build_record_response(refreshed or created_record)

    # --------------------------------------------------------------------------
    # 4. Action: REJECT
    # --------------------------------------------------------------------------

    async def reject_recovery(
        self,
        recovery_id: uuid.UUID,
        data: RejectVerificationRequest,
        requester: User,
    ) -> VerificationRecordResponse:
        """Reject recovery verification with mandatory rationale, preserving all evidence."""
        if requester.role not in [UserRole.VERIFIER, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only certified Verifiers or Super Admins can reject recovery events.")

        clean_reason = data.reason.strip() if data.reason else ""
        if not clean_reason:
            raise BadRequestException("A non-empty rejection reason is required.")

        # Atomic lock on the RecoveryEvent row
        recovery = await self.verification_repo.get_recovery_for_update(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' was not found.")

        # Authorization check
        await self._assert_verifier_organization_authorized(recovery, requester)

        # Self-verification prevention
        if recovery.collector_id == requester.id:
            raise BadRequestException("Self-verification is strictly prohibited: Verifiers cannot audit their own collection events.")

        # Cannot reject an already verified or cancelled batch
        if recovery.status == RecoveryStatus.VERIFIED:
            raise BadRequestException("Cannot reject a recovery event that is already VERIFIED.")
        if recovery.status == RecoveryStatus.CANCELLED:
            raise BadRequestException("Cannot reject a CANCELLED recovery event.")

        verification_code = f"VRF-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"
        org_id = requester.organization_id or recovery.program.organization_id

        # 1. Create immutable VerificationRecord
        record = VerificationRecord(
            verification_code=verification_code,
            recovery_id=recovery.id,
            verifier_id=requester.id,
            verifier_organization_id=org_id,
            decision=VerificationDecision.REJECTED,
            verified_weight_kg=None,
            reason=clean_reason,
            notes=data.notes,
            checklist={},
        )
        created_record = await self.verification_repo.create_record(record)

        # 2. Create corresponding critical finding
        finding = VerificationFinding(
            recovery_id=recovery.id,
            verification_record_id=created_record.id,
            finder_id=requester.id,
            severity=FindingSeverity.CRITICAL,
            category=FindingCategory.DOCUMENTATION.value,
            title="Verification Rejected",
            description=clean_reason,
            is_resolved=False,
        )
        await self.verification_repo.create_finding(finding)

        # 3. Advance Chain of Custody to REJECTED
        await self.custody_service.transition_custody(
            recovery.id,
            CustodyTransitionRequest(
                new_state=CustodyState.REJECTED,
                notes=clean_reason,
                metadata={
                    "verification_code": verification_code,
                    "rejection_reason": clean_reason,
                    "verifier_email": requester.email,
                },
            ),
            requester,
        )

        # 4. Transition RecoveryEvent to REJECTED (Preserving all evidence!)
        from_status = recovery.status.value
        recovery.status = RecoveryStatus.REJECTED

        await self.verification_repo.session.flush()

        # 5. Record state history & audit log
        await self.history_repo.record_transition(
            recovery_event_id=recovery.id,
            from_status=from_status,
            to_status=RecoveryStatus.REJECTED.value,
            actor_id=requester.id,
            actor_role=requester.role.value,
            notes=clean_reason,
            event_metadata={
                "verification_code": verification_code,
                "rejection_reason": clean_reason,
            },
        )

        await self.audit_repo.record(
            action="RECOVERY_REJECTED",
            resource=f"recovery:{recovery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "verification_code": verification_code,
                "reason": clean_reason,
                "decision": VerificationDecision.REJECTED.value,
            },
        )

        self.logger.warning(
            f"Recovery Event {recovery.recovery_id} REJECTED by {requester.email}: {clean_reason}"
        )

        refreshed = await self.verification_repo.get_record_by_id(created_record.id)
        return self._build_record_response(refreshed or created_record)

    # --------------------------------------------------------------------------
    # 5. Action: FLAG / REQUEST_REVIEW
    # --------------------------------------------------------------------------

    async def flag_recovery(
        self,
        recovery_id: uuid.UUID,
        data: FlagVerificationRequest,
        requester: User,
    ) -> VerificationRecordResponse:
        """Flag recovery event or request additional review (reason mandatory)."""
        if requester.role not in [UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Access denied: Only Verifiers, Auditors, or Admins can flag recovery events.")

        clean_reason = data.reason.strip() if data.reason else ""
        if not clean_reason:
            raise BadRequestException("A non-empty reason is required to flag a recovery event.")

        # Atomic lock on the RecoveryEvent row
        recovery = await self.verification_repo.get_recovery_for_update(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' was not found.")

        await self._assert_verifier_organization_authorized(recovery, requester)

        if recovery.status in [RecoveryStatus.VERIFIED]:
            raise BadRequestException("Cannot flag a recovery event that is already VERIFIED.")
        if recovery.status == RecoveryStatus.CANCELLED:
            raise BadRequestException("Cannot flag a CANCELLED recovery event.")

        verification_code = f"VRF-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"
        org_id = requester.organization_id or recovery.program.organization_id

        # 1. Create VerificationRecord
        record = VerificationRecord(
            verification_code=verification_code,
            recovery_id=recovery.id,
            verifier_id=requester.id,
            verifier_organization_id=org_id,
            decision=VerificationDecision.FLAGGED,
            verified_weight_kg=None,
            reason=clean_reason,
            notes=data.notes,
            checklist={},
        )
        created_record = await self.verification_repo.create_record(record)

        # 2. Create VerificationFinding
        finding = VerificationFinding(
            recovery_id=recovery.id,
            verification_record_id=created_record.id,
            finder_id=requester.id,
            severity=data.severity,
            category=data.category.value,
            title="Flagged during verification review",
            description=clean_reason,
            is_resolved=False,
        )
        await self.verification_repo.create_finding(finding)

        # 3. Transition RecoveryEvent status to FLAGGED
        from_status = recovery.status.value
        recovery.status = RecoveryStatus.FLAGGED

        await self.verification_repo.session.flush()

        # 4. Record history and audit
        await self.history_repo.record_transition(
            recovery_event_id=recovery.id,
            from_status=from_status,
            to_status=RecoveryStatus.FLAGGED.value,
            actor_id=requester.id,
            actor_role=requester.role.value,
            notes=clean_reason,
            event_metadata={
                "verification_code": verification_code,
                "flag_reason": clean_reason,
                "severity": data.severity.value,
            },
        )

        await self.audit_repo.record(
            action="RECOVERY_FLAGGED_FOR_REVIEW",
            resource=f"recovery:{recovery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "verification_code": verification_code,
                "reason": clean_reason,
                "severity": data.severity.value,
            },
        )

        refreshed = await self.verification_repo.get_record_by_id(created_record.id)
        return self._build_record_response(refreshed or created_record)

    # --------------------------------------------------------------------------
    # 6. Discrete Findings Management
    # --------------------------------------------------------------------------

    async def add_finding(
        self,
        recovery_id: uuid.UUID,
        data: VerificationFindingCreateRequest,
        requester: User,
    ) -> VerificationFindingResponse:
        """Register a specific audit finding or Sentinel flag."""
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' was not found.")

        await self._assert_verifier_organization_authorized(recovery, requester)

        finding = VerificationFinding(
            recovery_id=recovery.id,
            verification_record_id=None,
            finder_id=requester.id,
            severity=data.severity,
            category=data.category.value,
            title=data.title.strip(),
            description=data.description.strip(),
            is_resolved=False,
        )
        created = await self.verification_repo.create_finding(finding)

        await self.audit_repo.record(
            action="VERIFICATION_FINDING_RECORDED",
            resource=f"recovery:{recovery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={"finding_id": str(created.id), "severity": data.severity.value},
        )

        refreshed = await self.verification_repo.get_finding_by_id(created.id)
        return self._build_finding_response(refreshed or created)

    async def resolve_finding(
        self,
        finding_id: uuid.UUID,
        data: VerificationFindingResolveRequest,
        requester: User,
    ) -> VerificationFindingResponse:
        """Resolve a previously logged audit discrepancy."""
        finding = await self.verification_repo.get_finding_by_id(finding_id)
        if not finding:
            raise NotFoundException(f"Verification finding '{finding_id}' was not found.")

        recovery = await self.recovery_repo.get_by_id(finding.recovery_id)
        if recovery:
            await self._assert_verifier_organization_authorized(recovery, requester)

        finding.is_resolved = True
        finding.resolution_notes = data.resolution_notes.strip()
        finding.resolved_by_id = requester.id
        finding.resolved_at = datetime.now(timezone.utc)

        await self.verification_repo.session.flush()

        await self.audit_repo.record(
            action="VERIFICATION_FINDING_RESOLVED",
            resource=f"finding:{finding.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={"finding_id": str(finding.id)},
        )

        refreshed = await self.verification_repo.get_finding_by_id(finding.id)
        return self._build_finding_response(refreshed or finding)

    async def list_recovery_records(
        self, recovery_id: uuid.UUID, requester: User
    ) -> List[VerificationRecordResponse]:
        """List all verification determinations for a recovery event."""
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException("Recovery event not found.")
        await self._assert_can_view_verification_package(recovery, requester)
        records = await self.verification_repo.list_records_by_recovery(recovery_id)
        return [self._build_record_response(r) for r in records]

    # --------------------------------------------------------------------------
    # Internal Helpers & Authorization
    # --------------------------------------------------------------------------

    async def _assert_verifier_organization_authorized(
        self, recovery: RecoveryEvent, user: User
    ) -> None:
        """Ensure verifier belongs to an authorized partner organization on the program."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if not user.organization_id:
            raise ForbiddenException("Access denied: Verifiers must belong to a verified organization.")

        is_assigned = await self.program_partner_repo.is_partner_assigned(
            recovery.program_id, user.organization_id
        )
        if not is_assigned:
            raise ForbiddenException(
                "Access denied: Your organization is not an assigned partner for this recovery program."
            )

    async def _assert_can_view_verification_package(
        self, recovery: RecoveryEvent, user: User
    ) -> None:
        """Enforce tenant isolation on verification packages."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        user_org = user.organization_id
        if not user_org:
            raise ForbiddenException("Access denied.")

        # 1. Program owner Corporate
        program = await self.program_repo.get_by_id(recovery.program_id)
        if program and user_org == program.organization_id:
            return

        # 2. Assigned operational partner (Verifier, Auditor, Logistics, Recycler)
        if await self.program_partner_repo.is_partner_assigned(recovery.program_id, user_org):
            return

        # 3. Collector organization
        if user_org == recovery.collector_organization_id:
            return

        raise ForbiddenException("Access denied: You do not have permission to inspect this verification package.")

    def _build_record_response(self, record: VerificationRecord) -> VerificationRecordResponse:
        """Construct VerificationRecordResponse DTO."""
        findings_resp = [self._build_finding_response(f) for f in record.findings] if record.findings else []
        return VerificationRecordResponse(
            id=record.id,
            verification_code=record.verification_code,
            recovery_id=record.recovery_id,
            recovery_human_id=record.recovery.recovery_id if record.recovery else None,
            verifier_id=record.verifier_id,
            verifier_name=record.verifier.full_name if record.verifier else None,
            verifier_organization_id=record.verifier_organization_id,
            verifier_organization_name=record.verifier_organization.name
            if record.verifier_organization
            else None,
            decision=record.decision,
            verified_weight_kg=record.verified_weight_kg,
            reason=record.reason,
            notes=record.notes,
            checklist=record.checklist,
            created_at=record.created_at,
            findings=findings_resp,
        )

    def _build_finding_response(self, finding: VerificationFinding) -> VerificationFindingResponse:
        """Construct VerificationFindingResponse DTO."""
        return VerificationFindingResponse(
            id=finding.id,
            recovery_id=finding.recovery_id,
            verification_record_id=finding.verification_record_id,
            finder_id=finding.finder_id,
            finder_name=finding.finder.full_name if finding.finder else None,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            description=finding.description,
            is_resolved=finding.is_resolved,
            resolution_notes=finding.resolution_notes,
            resolved_by_id=finding.resolved_by_id,
            resolved_by_name=finding.resolved_by.full_name if finding.resolved_by else None,
            resolved_at=finding.resolved_at,
            created_at=finding.created_at,
        )

    def _build_assignment_response(self, assignment) -> LogisticsAssignmentResponse:
        delivery_resp = None
        if assignment.delivery:
            delivery_resp = self._build_delivery_response(assignment.delivery)

        return LogisticsAssignmentResponse(
            id=assignment.id,
            assignment_code=assignment.assignment_code,
            recovery_id=assignment.recovery_id,
            recovery_human_id=assignment.recovery.recovery_id if assignment.recovery else None,
            program_id=assignment.program_id,
            program_name=assignment.program.name if assignment.program else None,
            logistics_organization_id=assignment.logistics_organization_id,
            logistics_organization_name=assignment.logistics_organization.name
            if assignment.logistics_organization
            else None,
            destination_organization_id=assignment.destination_organization_id,
            destination_organization_name=assignment.destination_organization.name
            if assignment.destination_organization
            else None,
            assigned_by_id=assignment.assigned_by_id,
            assigned_by_name=assignment.assigned_by.full_name if assignment.assigned_by else None,
            assigned_to_driver_id=assignment.assigned_to_driver_id,
            assigned_to_driver_name=assignment.assigned_to_driver.full_name
            if assignment.assigned_to_driver
            else None,
            status=assignment.status,
            pickup_location=assignment.pickup_location,
            destination_location=assignment.destination_location,
            scheduled_pickup_date=assignment.scheduled_pickup_date,
            expected_weight_kg=assignment.recovery.weight_kg if assignment.recovery else 0.0,
            notes=assignment.notes,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
            delivery=delivery_resp,
        )

    def _build_delivery_response(self, delivery) -> DeliveryResponse:
        ev_records = []
        if delivery.evidence_records:
            for ev in delivery.evidence_records:
                ev_records.append(
                    DeliveryEvidenceResponse(
                        id=ev.id,
                        delivery_id=ev.delivery_id,
                        evidence_id=ev.evidence_id,
                        uploader_id=ev.uploader_id,
                        uploader_name=ev.uploader.full_name if ev.uploader else None,
                        evidence_type=ev.evidence_type,
                        original_filename=ev.original_filename,
                        mime_type=ev.mime_type,
                        file_size=ev.file_size,
                        sha256_hash=ev.sha256_hash,
                        notes=ev.notes,
                        created_at=ev.created_at,
                    )
                )

        return DeliveryResponse(
            id=delivery.id,
            delivery_code=delivery.delivery_code,
            assignment_id=delivery.assignment_id,
            recovery_id=delivery.recovery_id,
            recovery_human_id=delivery.recovery.recovery_id if delivery.recovery else None,
            logistics_organization_id=delivery.logistics_organization_id,
            logistics_organization_name=delivery.logistics_organization.name
            if delivery.logistics_organization
            else None,
            recycler_organization_id=delivery.recycler_organization_id,
            recycler_organization_name=delivery.recycler_organization.name
            if delivery.recycler_organization
            else None,
            driver_id=delivery.driver_id,
            driver_name=delivery.driver.full_name if delivery.driver else None,
            receiver_id=delivery.receiver_id,
            receiver_name=delivery.receiver.full_name if delivery.receiver else None,
            status=delivery.status,
            expected_weight_kg=delivery.expected_weight_kg,
            delivered_weight_kg=delivery.delivered_weight_kg,
            received_weight_kg=delivery.received_weight_kg,
            weight_discrepancy_kg=delivery.weight_discrepancy_kg,
            weight_tolerance_pct=delivery.weight_tolerance_pct,
            weight_tolerance_status=delivery.weight_tolerance_status,
            pickup_timestamp=delivery.pickup_timestamp,
            in_transit_timestamp=delivery.in_transit_timestamp,
            delivery_timestamp=delivery.delivery_timestamp,
            received_timestamp=delivery.received_timestamp,
            vehicle_number=delivery.vehicle_number,
            tracking_number=delivery.tracking_number,
            notes=delivery.notes,
            receipt_notes=delivery.receipt_notes,
            evidence_records=ev_records,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
        )

    async def _build_recovery_response(self, event: RecoveryEvent) -> RecoveryResponse:
        evidence_count = await self.evidence_repo.count_by_recovery(event.id)
        return RecoveryResponse(
            id=event.id,
            recovery_id=event.recovery_id,
            program_id=event.program_id,
            program_name=event.program.name if event.program else None,
            collector_id=event.collector_id,
            collector_name=event.collector.full_name if event.collector else None,
            collector_organization_id=event.collector_organization_id,
            collector_organization_name=event.collector_organization.name
            if event.collector_organization
            else None,
            material_type=event.material_type,
            weight_kg=event.weight_kg,
            collection_location=event.collection_location,
            collection_coordinates=event.collection_coordinates,
            collected_at=event.collected_at,
            status=event.status,
            custody_status=event.custody_status,
            evidence_count=evidence_count,
            notes=event.notes,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )
