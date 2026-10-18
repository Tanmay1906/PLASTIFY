"""PLASTIFY Logistics and Delivery Domain Service.

Orchestrates the complete physical materials movement workflow:
Recovery Event -> Pickup Assignment -> Pickup Accepted -> Picked Up -> In Transit -> Delivered -> Recycler Received.

Enforces:
- Server-side state transition validations (no delivery before pickup, no receipt before delivery)
- Multi-tenant organization boundaries and access controls
- Configurable weight tolerance verification (PASS vs FLAG_FOR_REVIEW)
- Seamless integration with the immutable Chain of Custody audit system
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.custody import ChainOfCustodyEvent, CustodyState
from app.models.logistics import (
    AssignmentStatus,
    Delivery,
    DeliveryEvidence,
    DeliveryStatus,
    LogisticsAssignment,
    WeightToleranceStatus,
)
from app.models.organization import OrganizationType
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.logistics import LogisticsRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.repositories.recovery import RecoveryRepository
from app.schemas.custody import CustodyTransitionRequest
from app.schemas.logistics import (
    AcceptAssignmentRequest,
    AssignLogisticsRequest,
    DeliveryEvidenceResponse,
    DeliveryHistoryResponse,
    DeliveryResponse,
    LogisticsAssignmentResponse,
    MarkDeliveredRequest,
    MarkInTransitRequest,
    MarkPickupRequest,
    RecyclerConfirmReceiptRequest,
)
from app.services.base import BaseService
from app.services.custody import ChainOfCustodyService


class LogisticsService(BaseService):
    """Domain service managing the physical collection, transportation, and delivery lifecycle."""

    def __init__(
        self,
        settings: Settings,
        logistics_repo: LogisticsRepository,
        recovery_repo: RecoveryRepository,
        organization_repo: OrganizationRepository,
        program_repo: ProgramRepository,
        program_partner_repo: ProgramPartnerRepository,
        custody_service: ChainOfCustodyService,
        audit_repo: AuditRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.logistics_repo = logistics_repo
        self.recovery_repo = recovery_repo
        self.organization_repo = organization_repo
        self.program_repo = program_repo
        self.program_partner_repo = program_partner_repo
        self.custody_service = custody_service
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. List Available Pickup Assignments
    # --------------------------------------------------------------------------

    async def list_available_assignments(
        self, requester: User, skip: int = 0, limit: int = 50
    ) -> List[LogisticsAssignmentResponse]:
        """List assignments ready for logistics pickup."""
        if requester.role == UserRole.SUPER_ADMIN:
            assignments = await self.logistics_repo.list_available_assignments(
                skip=skip, limit=limit
            )
        else:
            logistics_org_id = requester.organization_id
            if not logistics_org_id:
                return []

            # Find programs where requester's org is assigned as partner
            assignments = await self.logistics_repo.list_available_assignments(
                logistics_org_id=logistics_org_id,
                skip=skip,
                limit=limit,
            )

        return [self._build_assignment_response(a) for a in assignments]

    # --------------------------------------------------------------------------
    # 2. Assign Logistics Partner
    # --------------------------------------------------------------------------

    async def assign_logistics_partner(
        self, data: AssignLogisticsRequest, requester: User
    ) -> LogisticsAssignmentResponse:
        """Assign a recovery batch to a certified logistics carrier."""
        # 1. Fetch Recovery Event
        recovery = await self.recovery_repo.get_by_id(data.recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{data.recovery_id}' was not found.")

        # 2. State validation: recovery must be submitted and not already in transit/assigned
        if recovery.status == RecoveryStatus.DRAFT:
            raise BadRequestException(
                "Recovery event is still in DRAFT status. It must be SUBMITTED before assigning logistics."
            )

        existing_assignment = await self.logistics_repo.get_assignment_by_recovery_id(recovery.id)
        if existing_assignment and existing_assignment.status not in [AssignmentStatus.CANCELLED]:
            raise BadRequestException(
                f"Recovery event is already assigned to a logistics carrier (Assignment: {existing_assignment.assignment_code})."
            )

        # 3. Authorization: Super Admin, Program Corporate Owner, Collector creator, or assigned Logistics
        await self._assert_can_assign_logistics(recovery, requester)

        # 4. Verify Logistics Organization
        logistics_org = await self.organization_repo.get_by_id(data.logistics_organization_id)
        if not logistics_org:
            raise NotFoundException("Assigned logistics organization not found.")
        if logistics_org.org_type not in [OrganizationType.LOGISTICS, OrganizationType.CORPORATE]:
            raise BadRequestException(
                f"Target organization '{logistics_org.name}' is of type '{logistics_org.org_type.value}', expected LOGISTICS."
            )

        # 5. Verify Destination Recycler Organization (if provided)
        dest_location = data.destination_location
        if data.destination_organization_id:
            dest_org = await self.organization_repo.get_by_id(data.destination_organization_id)
            if not dest_org:
                raise NotFoundException("Destination recycling organization not found.")
            if dest_org.org_type not in [OrganizationType.RECYCLER, OrganizationType.UPCYCLER]:
                raise BadRequestException(
                    f"Destination organization must be RECYCLER or UPCYCLER, got '{dest_org.org_type.value}'."
                )
            if not dest_location:
                dest_location = dest_org.name

        # 6. Generate human-readable codes
        year = datetime.now(timezone.utc).year
        unique_suffix = uuid.uuid4().hex[:8].upper()
        assignment_code = f"LOG-{year}-{unique_suffix}"
        delivery_code = f"DEL-{year}-{unique_suffix}"

        # 7. Create LogisticsAssignment record
        assignment = LogisticsAssignment(
            assignment_code=assignment_code,
            recovery_id=recovery.id,
            program_id=recovery.program_id,
            logistics_organization_id=data.logistics_organization_id,
            destination_organization_id=data.destination_organization_id,
            assigned_by_id=requester.id,
            status=AssignmentStatus.ASSIGNED,
            pickup_location=recovery.collection_location,
            destination_location=dest_location,
            scheduled_pickup_date=data.scheduled_pickup_date,
            notes=data.notes.strip() if data.notes else None,
        )
        created_assignment = await self.logistics_repo.create_assignment(assignment)

        # 8. Create corresponding Delivery record
        delivery = Delivery(
            delivery_code=delivery_code,
            assignment_id=created_assignment.id,
            recovery_id=recovery.id,
            logistics_organization_id=data.logistics_organization_id,
            recycler_organization_id=data.destination_organization_id,
            status=DeliveryStatus.PENDING,
            expected_weight_kg=recovery.weight_kg,
            weight_tolerance_pct=self.settings.DEFAULT_WEIGHT_TOLERANCE_PERCENT,
            weight_tolerance_status=WeightToleranceStatus.PENDING,
            notes=data.notes.strip() if data.notes else None,
        )
        created_delivery = await self.logistics_repo.create_delivery(delivery)
        created_assignment.delivery = created_delivery

        # 9. Transition Chain of Custody to PICKUP_ASSIGNED
        current_custody = recovery.custody_status or CustodyState.CREATED.value
        if current_custody == CustodyState.CREATED.value:
            custody_event_sub = ChainOfCustodyEvent(
                resource=recovery.recovery_id,
                resource_type="RECOVERY_EVENT",
                resource_id=recovery.id,
                previous_state=CustodyState.CREATED.value,
                new_state=CustodyState.SUBMITTED.value,
                actor_id=recovery.collector_id,
                actor_role=UserRole.COLLECTOR.value,
                timestamp=datetime.now(timezone.utc),
                event_metadata={"note": "Batch submitted for transport"},
            )
            await self.custody_service.custody_repo.record_event(custody_event_sub)
            recovery.custody_status = CustodyState.SUBMITTED.value

        await self.custody_service.transition_custody(
            recovery.id,
            CustodyTransitionRequest(
                new_state=CustodyState.PICKUP_ASSIGNED,
                notes=f"Pickup assigned to {logistics_org.name} ({assignment_code})",
                metadata={
                    "assignment_id": str(created_assignment.id),
                    "assignment_code": assignment_code,
                    "logistics_organization_id": str(logistics_org.id),
                    "logistics_organization_name": logistics_org.name,
                },
            ),
            requester,
        )

        # 10. Audit Logging
        await self.audit_repo.record(
            action="LOGISTICS_ASSIGNED",
            resource=f"assignment:{created_assignment.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "recovery_id": str(recovery.id),
                "assignment_code": assignment_code,
                "logistics_org_id": str(logistics_org.id),
            },
        )

        self.logger.info(
            f"Logistics assignment {assignment_code} created for recovery {recovery.recovery_id} by {requester.email}"
        )

        refreshed = await self.logistics_repo.get_assignment_by_id(created_assignment.id)
        target = refreshed or created_assignment
        if not target.delivery:
            target.delivery = created_delivery
        return self._build_assignment_response(target)

    # --------------------------------------------------------------------------
    # 3. Accept Assignment
    # --------------------------------------------------------------------------

    async def accept_assignment(
        self,
        assignment_id: uuid.UUID,
        data: AcceptAssignmentRequest,
        requester: User,
    ) -> LogisticsAssignmentResponse:
        """Logistics carrier acknowledges and accepts transport task."""
        assignment = await self.logistics_repo.get_assignment_by_id(assignment_id)
        if not assignment:
            raise NotFoundException(f"Logistics assignment '{assignment_id}' was not found.")

        # State check
        if assignment.status != AssignmentStatus.ASSIGNED:
            raise BadRequestException(
                f"Assignment cannot be accepted from status '{assignment.status.value}'. Must be ASSIGNED."
            )

        # Multi-tenant boundary check
        self._assert_logistics_organization_member(assignment, requester)

        assignment.status = AssignmentStatus.ACCEPTED
        if data.assigned_to_driver_id:
            assignment.assigned_to_driver_id = data.assigned_to_driver_id
        if data.notes:
            assignment.notes = (
                f"{assignment.notes}\n[Acceptance]: {data.notes}"
                if assignment.notes
                else data.notes
            )

        await self.logistics_repo.session.flush()

        await self.audit_repo.record(
            action="ASSIGNMENT_ACCEPTED",
            resource=f"assignment:{assignment.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={"assignment_code": assignment.assignment_code},
        )

        refreshed = await self.logistics_repo.get_assignment_by_id(assignment.id)
        return self._build_assignment_response(refreshed or assignment)

    # --------------------------------------------------------------------------
    # 4. Mark Pickup Completed
    # --------------------------------------------------------------------------

    async def mark_pickup_completed(
        self,
        assignment_id: uuid.UUID,
        data: MarkPickupRequest,
        requester: User,
    ) -> LogisticsAssignmentResponse:
        """Mark physical collection from collector completed and seal transport."""
        assignment = await self.logistics_repo.get_assignment_by_id(assignment_id)
        if not assignment:
            raise NotFoundException(f"Logistics assignment '{assignment_id}' was not found.")

        # State validation: cannot deliver before pickup
        if assignment.status not in [AssignmentStatus.ASSIGNED, AssignmentStatus.ACCEPTED]:
            raise BadRequestException(
                f"Invalid state transition: Pickup cannot be completed from status '{assignment.status.value}'."
            )

        # Multi-tenant boundary check
        self._assert_logistics_organization_member(assignment, requester)

        pickup_time = data.pickup_timestamp or datetime.now(timezone.utc)
        assignment.status = AssignmentStatus.PICKED_UP

        delivery = await self.logistics_repo.get_delivery_by_assignment_id(assignment.id)
        if delivery:
            delivery.status = DeliveryStatus.PICKED_UP
            delivery.pickup_timestamp = pickup_time
            if data.vehicle_number:
                delivery.vehicle_number = data.vehicle_number
            if data.driver_id:
                delivery.driver_id = data.driver_id
            elif not delivery.driver_id:
                delivery.driver_id = requester.id
            if data.notes:
                delivery.notes = (
                    f"{delivery.notes}\n[Pickup]: {data.notes}"
                    if delivery.notes
                    else data.notes
                )

        await self.logistics_repo.session.flush()

        # Advance Chain of Custody to PICKED_UP
        await self.custody_service.transition_custody(
            assignment.recovery_id,
            CustodyTransitionRequest(
                new_state=CustodyState.PICKED_UP,
                notes=data.notes or f"Material batch picked up ({assignment.assignment_code})",
                metadata={
                    "assignment_code": assignment.assignment_code,
                    "vehicle_number": data.vehicle_number,
                    "pickup_timestamp": pickup_time.isoformat(),
                },
            ),
            requester,
        )

        await self.audit_repo.record(
            action="PICKUP_COMPLETED",
            resource=f"assignment:{assignment.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={"assignment_code": assignment.assignment_code},
        )

        refreshed = await self.logistics_repo.get_assignment_by_id(assignment.id)
        target = refreshed or assignment
        if not target.delivery and delivery:
            target.delivery = delivery
        return self._build_assignment_response(target)

    # --------------------------------------------------------------------------
    # 5. Mark In Transit
    # --------------------------------------------------------------------------

    async def mark_in_transit(
        self,
        identifier: uuid.UUID,
        data: MarkInTransitRequest,
        requester: User,
    ) -> DeliveryResponse:
        """Update material movement status to IN_TRANSIT."""
        delivery = await self._find_delivery(identifier)
        if not delivery:
            raise NotFoundException(f"Delivery record for '{identifier}' not found.")

        # Validation: Must be picked up first! Cannot mark in transit before pickup
        if delivery.status != DeliveryStatus.PICKED_UP:
            raise BadRequestException(
                f"Invalid state transition: Cannot mark in-transit before pickup. Current status is '{delivery.status.value}'."
            )

        self._assert_logistics_organization_member_delivery(delivery, requester)

        transit_time = data.in_transit_timestamp or datetime.now(timezone.utc)
        delivery.status = DeliveryStatus.IN_TRANSIT
        delivery.in_transit_timestamp = transit_time
        if data.tracking_number:
            delivery.tracking_number = data.tracking_number
        if data.notes:
            delivery.notes = (
                f"{delivery.notes}\n[Transit]: {data.notes}"
                if delivery.notes
                else data.notes
            )

        # Update assignment
        if delivery.assignment:
            delivery.assignment.status = AssignmentStatus.IN_TRANSIT

        await self.logistics_repo.session.flush()

        # Advance Chain of Custody to IN_TRANSIT
        await self.custody_service.transition_custody(
            delivery.recovery_id,
            CustodyTransitionRequest(
                new_state=CustodyState.IN_TRANSIT,
                notes=data.notes or f"Shipment in transit ({delivery.delivery_code})",
                metadata={
                    "delivery_code": delivery.delivery_code,
                    "tracking_number": data.tracking_number,
                    "current_location": data.current_location,
                },
            ),
            requester,
        )

        await self.audit_repo.record(
            action="SHIPMENT_IN_TRANSIT",
            resource=f"delivery:{delivery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={"delivery_code": delivery.delivery_code},
        )

        refreshed = await self.logistics_repo.get_delivery_by_id(delivery.id)
        return self._build_delivery_response(refreshed or delivery)

    # --------------------------------------------------------------------------
    # 6. Mark Delivered
    # --------------------------------------------------------------------------

    async def mark_delivered(
        self,
        identifier: uuid.UUID,
        data: MarkDeliveredRequest,
        requester: User,
    ) -> DeliveryResponse:
        """Carrier marks arrival and physical drop-off at destination facility."""
        delivery = await self._find_delivery(identifier)
        if not delivery:
            raise NotFoundException(f"Delivery record for '{identifier}' not found.")

        # Server-side validation: A user cannot deliver before pickup!
        if delivery.status in [DeliveryStatus.PENDING]:
            raise BadRequestException(
                "Invalid state transition: Cannot mark delivered before pickup has been completed."
            )
        if delivery.status not in [DeliveryStatus.IN_TRANSIT, DeliveryStatus.PICKED_UP]:
            raise BadRequestException(
                f"Invalid state transition: Delivery is already in '{delivery.status.value}' status."
            )

        self._assert_logistics_organization_member_delivery(delivery, requester)

        deliv_time = data.delivery_timestamp or datetime.now(timezone.utc)
        delivered_weight = data.delivered_weight_kg or delivery.expected_weight_kg

        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivery_timestamp = deliv_time
        delivery.delivered_weight_kg = delivered_weight
        if data.notes:
            delivery.notes = (
                f"{delivery.notes}\n[Delivered]: {data.notes}"
                if delivery.notes
                else data.notes
            )

        if delivery.assignment:
            delivery.assignment.status = AssignmentStatus.DELIVERED

        # Link any existing evidence IDs
        if data.evidence_ids:
            for ev_id in data.evidence_ids:
                deliv_evidence = DeliveryEvidence(
                    delivery_id=delivery.id,
                    evidence_id=ev_id,
                    uploader_id=requester.id,
                    evidence_type="DELIVERY_PROOF",
                    notes="Attached upon delivery completion",
                )
                deliv_evidence.uploader = requester
                created_ev = await self.logistics_repo.create_delivery_evidence(deliv_evidence)
                delivery.evidence_records.append(created_ev)

        await self.logistics_repo.session.flush()

        # Advance Chain of Custody to DELIVERED
        await self.custody_service.transition_custody(
            delivery.recovery_id,
            CustodyTransitionRequest(
                new_state=CustodyState.DELIVERED,
                notes=data.notes or f"Shipment delivered at destination ({delivery.delivery_code})",
                metadata={
                    "delivery_code": delivery.delivery_code,
                    "delivered_weight_kg": delivered_weight,
                    "delivery_timestamp": deliv_time.isoformat(),
                },
            ),
            requester,
        )

        await self.audit_repo.record(
            action="SHIPMENT_DELIVERED",
            resource=f"delivery:{delivery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "delivery_code": delivery.delivery_code,
                "delivered_weight_kg": delivered_weight,
            },
        )

        refreshed = await self.logistics_repo.get_delivery_by_id(delivery.id)
        return self._build_delivery_response(refreshed or delivery)

    # --------------------------------------------------------------------------
    # 7. Recycler Confirms Receipt & Weight Tolerance Verification
    # --------------------------------------------------------------------------

    async def recycler_confirm_receipt(
        self,
        delivery_id: uuid.UUID,
        data: RecyclerConfirmReceiptRequest,
        requester: User,
    ) -> DeliveryResponse:
        """Receiving recycling facility confirms receipt, weighs shipment, and verifies tolerance."""
        delivery = await self._find_delivery(delivery_id)
        if not delivery:
            raise NotFoundException(f"Delivery '{delivery_id}' was not found.")

        # Server-side validation: A user cannot receive before delivery!
        if delivery.status != DeliveryStatus.DELIVERED:
            raise BadRequestException(
                f"Invalid state transition: Cannot confirm receipt before shipment has been delivered. Current status is '{delivery.status.value}'."
            )

        # Multi-tenant boundary check: Only designated recycler organization (or Super Admin) can receive
        self._assert_recycler_organization_member(delivery, requester)

        # ----------------------------------------------------------------------
        # Configurable Weight Tolerance Evaluation:
        # Expected/Delivered vs Received Weight
        # ----------------------------------------------------------------------
        baseline_weight = delivery.delivered_weight_kg or delivery.expected_weight_kg
        received_weight = data.received_weight_kg

        weight_discrepancy_kg = round(abs(baseline_weight - received_weight), 3)
        discrepancy_pct = (
            (weight_discrepancy_kg / baseline_weight) * 100.0 if baseline_weight > 0 else 0.0
        )
        tolerance_pct = delivery.weight_tolerance_pct or self.settings.DEFAULT_WEIGHT_TOLERANCE_PERCENT

        # If within tolerance: PASS; If outside tolerance: FLAG_FOR_REVIEW (never automatic fraud)
        if discrepancy_pct <= tolerance_pct:
            tolerance_status = WeightToleranceStatus.PASS
            evaluation_note = f"Weight verified: discrepancy of {weight_discrepancy_kg}kg ({discrepancy_pct:.2f}%) within allowable +/-{tolerance_pct}% tolerance."
        else:
            tolerance_status = WeightToleranceStatus.FLAG_FOR_REVIEW
            evaluation_note = (
                f"Weight discrepancy detected: received {received_weight}kg vs baseline {baseline_weight}kg "
                f"(variance: {weight_discrepancy_kg}kg / {discrepancy_pct:.2f}%). Exceeds +/-{tolerance_pct}% tolerance. "
                f"Flagged for human verification review."
            )

        received_time = data.received_timestamp or datetime.now(timezone.utc)

        delivery.status = DeliveryStatus.RECEIVED
        delivery.receiver_id = requester.id
        delivery.received_weight_kg = received_weight
        delivery.weight_discrepancy_kg = weight_discrepancy_kg
        delivery.weight_tolerance_status = tolerance_status
        delivery.received_timestamp = received_time
        delivery.receipt_notes = (
            f"{data.receipt_notes}\n[Evaluation]: {evaluation_note}"
            if data.receipt_notes
            else evaluation_note
        )

        if not delivery.recycler_organization_id and requester.organization_id:
            delivery.recycler_organization_id = requester.organization_id

        if delivery.assignment:
            delivery.assignment.status = AssignmentStatus.COMPLETED

        # Link any receiving evidence records
        if data.evidence_ids:
            for ev_id in data.evidence_ids:
                deliv_evidence = DeliveryEvidence(
                    delivery_id=delivery.id,
                    evidence_id=ev_id,
                    uploader_id=requester.id,
                    evidence_type="RECEIPT",
                    notes="Attached upon recycler intake",
                )
                deliv_evidence.uploader = requester
                created_ev = await self.logistics_repo.create_delivery_evidence(deliv_evidence)
                delivery.evidence_records.append(created_ev)

        await self.logistics_repo.session.flush()

        # Advance Chain of Custody to RECEIVED
        await self.custody_service.transition_custody(
            delivery.recovery_id,
            CustodyTransitionRequest(
                new_state=CustodyState.RECEIVED,
                notes=delivery.receipt_notes,
                metadata={
                    "delivery_code": delivery.delivery_code,
                    "received_weight_kg": received_weight,
                    "weight_tolerance_status": tolerance_status.value,
                    "weight_discrepancy_kg": weight_discrepancy_kg,
                    "discrepancy_pct": round(discrepancy_pct, 2),
                },
            ),
            requester,
        )

        await self.audit_repo.record(
            action="RECYCLER_RECEIPT_CONFIRMED",
            resource=f"delivery:{delivery.id}",
            actor_id=requester.id,
            actor_email=requester.email,
            actor_role=requester.role.value,
            metadata={
                "delivery_code": delivery.delivery_code,
                "received_weight_kg": received_weight,
                "tolerance_status": tolerance_status.value,
                "discrepancy_kg": weight_discrepancy_kg,
            },
        )

        self.logger.info(
            f"Delivery {delivery.delivery_code} confirmed by recycler {requester.email}. "
            f"Weight status: {tolerance_status.value} (diff: {weight_discrepancy_kg}kg)"
        )

        refreshed = await self.logistics_repo.get_delivery_by_id(delivery.id)
        return self._build_delivery_response(refreshed or delivery)

    # --------------------------------------------------------------------------
    # 8. View Delivery History & Timeline
    # --------------------------------------------------------------------------

    async def get_delivery_history(
        self, delivery_id: uuid.UUID, requester: User
    ) -> DeliveryHistoryResponse:
        """Fetch delivery details alongside complete immutable chain-of-custody timeline."""
        delivery = await self._find_delivery(delivery_id)
        if not delivery:
            raise NotFoundException(f"Delivery '{delivery_id}' was not found.")

        # Multi-tenant boundary verification
        self._assert_can_view_delivery(delivery, requester)

        timeline = await self.custody_service.get_custody_timeline(
            delivery.recovery_id, requester
        )

        return DeliveryHistoryResponse(
            delivery=self._build_delivery_response(delivery),
            custody_events=timeline.events,
        )

    # --------------------------------------------------------------------------
    # 9. List Deliveries (Filtered by Organization Boundaries)
    # --------------------------------------------------------------------------

    async def list_deliveries(
        self,
        requester: User,
        status: Optional[DeliveryStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[DeliveryResponse]:
        """List deliveries honoring tenant boundaries."""
        if requester.role == UserRole.SUPER_ADMIN:
            deliveries = await self.logistics_repo.list_deliveries(
                status=status, skip=skip, limit=limit
            )
        elif requester.role in [UserRole.LOGISTICS]:
            deliveries = await self.logistics_repo.list_deliveries(
                logistics_org_id=requester.organization_id,
                status=status,
                skip=skip,
                limit=limit,
            )
        elif requester.role in [UserRole.RECYCLER, UserRole.UPCYCLER]:
            deliveries = await self.logistics_repo.list_deliveries(
                recycler_org_id=requester.organization_id,
                status=status,
                skip=skip,
                limit=limit,
            )
        else:
            # Corporate or other roles: return deliveries for their programs
            deliveries = await self.logistics_repo.list_deliveries(
                status=status, skip=skip, limit=limit
            )
            # Filter in Python by authorized organization
            deliveries = [
                d
                for d in deliveries
                if self._can_view_delivery_filter(d, requester)
            ]

        return [self._build_delivery_response(d) for d in deliveries]

    async def get_delivery(self, delivery_id: uuid.UUID, requester: User) -> DeliveryResponse:
        """Get single delivery record."""
        delivery = await self._find_delivery(delivery_id)
        if not delivery:
            raise NotFoundException(f"Delivery '{delivery_id}' was not found.")
        self._assert_can_view_delivery(delivery, requester)
        return self._build_delivery_response(delivery)

    async def get_assignment(
        self, assignment_id: uuid.UUID, requester: User
    ) -> LogisticsAssignmentResponse:
        """Get single assignment record."""
        assignment = await self.logistics_repo.get_assignment_by_id(assignment_id)
        if not assignment:
            raise NotFoundException(f"Logistics assignment '{assignment_id}' was not found.")
        self._assert_can_view_assignment(assignment, requester)
        return self._build_assignment_response(assignment)

    # --------------------------------------------------------------------------
    # Internal Authorization Helpers & Resolvers
    # --------------------------------------------------------------------------

    async def _find_delivery(self, identifier: uuid.UUID) -> Optional[Delivery]:
        """Look up delivery by delivery ID or assignment ID."""
        delivery = await self.logistics_repo.get_delivery_by_id(identifier)
        if not delivery:
            delivery = await self.logistics_repo.get_delivery_by_assignment_id(identifier)
        return delivery

    async def _assert_can_assign_logistics(self, recovery: RecoveryEvent, user: User) -> None:
        """Enforce authorization to assign logistics carrier."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        # 1. Collector who created recovery event
        if recovery.collector_id == user.id:
            return

        # 2. Member of creating collector organization
        if user.organization_id and user.organization_id == recovery.collector_organization_id:
            return

        # 3. Corporate brand owner of the program
        program = await self.program_repo.get_by_id(recovery.program_id)
        if program and user.organization_id and user.organization_id == program.organization_id:
            return

        # 4. Assigned operational partner organization
        if user.organization_id and await self.program_partner_repo.is_partner_assigned(
            recovery.program_id, user.organization_id
        ):
            return

        raise ForbiddenException(
            "Access denied: You do not have permission to assign logistics for this recovery event."
        )

    def _assert_logistics_organization_member(
        self, assignment: LogisticsAssignment, user: User
    ) -> None:
        """Ensure requester belongs to the assigned logistics organization."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if (
            not user.organization_id
            or user.organization_id != assignment.logistics_organization_id
        ):
            raise ForbiddenException(
                "Access denied: Only members of the assigned logistics organization can execute this action."
            )

    def _assert_logistics_organization_member_delivery(
        self, delivery: Delivery, user: User
    ) -> None:
        """Ensure requester belongs to the delivery's logistics organization."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if (
            not user.organization_id
            or user.organization_id != delivery.logistics_organization_id
        ):
            raise ForbiddenException(
                "Access denied: Only members of the assigned logistics organization can manage this delivery."
            )

    def _assert_recycler_organization_member(self, delivery: Delivery, user: User) -> None:
        """Ensure requester belongs to the designated recycler organization."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if delivery.recycler_organization_id:
            if (
                not user.organization_id
                or user.organization_id != delivery.recycler_organization_id
            ):
                raise ForbiddenException(
                    "Access denied: Only members of the designated recipient recycling organization can confirm receipt."
                )
        else:
            if user.role not in [UserRole.RECYCLER, UserRole.UPCYCLER]:
                raise ForbiddenException(
                    "Access denied: Only Recycler or Upcycler roles can confirm delivery intake."
                )

    def _assert_can_view_delivery(self, delivery: Delivery, user: User) -> None:
        """Ensure user belongs to an involved party."""
        if not self._can_view_delivery_filter(delivery, user):
            raise ForbiddenException(
                "Access denied: You do not have permission to view this delivery."
            )

    def _can_view_delivery_filter(self, delivery: Delivery, user: User) -> bool:
        """Check if user has permission to view delivery."""
        if user.role == UserRole.SUPER_ADMIN:
            return True

        user_org = user.organization_id
        if not user_org:
            return False

        if user_org == delivery.logistics_organization_id:
            return True
        if delivery.recycler_organization_id and user_org == delivery.recycler_organization_id:
            return True

        if delivery.recovery:
            if user_org == delivery.recovery.collector_organization_id:
                return True
            if delivery.recovery.program and user_org == delivery.recovery.program.organization_id:
                return True

        return False

    def _assert_can_view_assignment(self, assignment: LogisticsAssignment, user: User) -> None:
        """Ensure user belongs to an involved party for the assignment."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        user_org = user.organization_id
        if not user_org:
            raise ForbiddenException("Access denied.")

        if user_org == assignment.logistics_organization_id:
            return
        if assignment.destination_organization_id and user_org == assignment.destination_organization_id:
            return
        if assignment.recovery and user_org == assignment.recovery.collector_organization_id:
            return
        if assignment.program and user_org == assignment.program.organization_id:
            return

        raise ForbiddenException("Access denied: You do not have permission to view this assignment.")

    def _build_delivery_response(self, delivery: Delivery) -> DeliveryResponse:
        """Construct detailed DeliveryResponse DTO."""
        ev_records = []
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

    def _build_assignment_response(
        self, assignment: LogisticsAssignment
    ) -> LogisticsAssignmentResponse:
        """Construct detailed LogisticsAssignmentResponse DTO."""
        delivery_res = (
            self._build_delivery_response(assignment.delivery)
            if assignment.delivery
            else None
        )

        return LogisticsAssignmentResponse(
            id=assignment.id,
            assignment_code=assignment.assignment_code,
            recovery_id=assignment.recovery_id,
            recovery_human_id=assignment.recovery.recovery_id
            if assignment.recovery
            else None,
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
            assigned_by_name=assignment.assigned_by.full_name
            if assignment.assigned_by
            else None,
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
            delivery=delivery_res,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )
