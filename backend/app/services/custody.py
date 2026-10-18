"""PLASTIFY Chain-of-Custody Domain Service.

Enforces state transition rules, role-based custody milestones, and append-only
immutable audit tracking across the circular materials custody chain.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.custody import ChainOfCustodyEvent, CustodyState
from app.models.recovery import RecoveryEvent, RecoveryStatus
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.custody import ChainOfCustodyRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.repositories.recovery import RecoveryRepository
from app.schemas.custody import (
    CustodyEventResponse,
    CustodyTimelineResponse,
    CustodyTransitionRequest,
)
from app.services.base import BaseService

# Valid state progression graph
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    CustodyState.CREATED.value: {CustodyState.SUBMITTED.value, CustodyState.REJECTED.value},
    CustodyState.SUBMITTED.value: {CustodyState.PICKUP_ASSIGNED.value, CustodyState.REJECTED.value},
    CustodyState.PICKUP_ASSIGNED.value: {CustodyState.PICKED_UP.value, CustodyState.REJECTED.value},
    CustodyState.PICKED_UP.value: {CustodyState.IN_TRANSIT.value, CustodyState.REJECTED.value},
    CustodyState.IN_TRANSIT.value: {CustodyState.DELIVERED.value, CustodyState.REJECTED.value},
    CustodyState.DELIVERED.value: {CustodyState.RECEIVED.value, CustodyState.REJECTED.value},
    CustodyState.RECEIVED.value: {CustodyState.VERIFIED.value, CustodyState.REJECTED.value},
    CustodyState.VERIFIED.value: {CustodyState.PROCESSED.value},
    CustodyState.PROCESSED.value: set(),
    CustodyState.REJECTED.value: set(),
}

# Role authorizations required to trigger specific state transitions
ROLE_STATE_PERMISSIONS: Dict[str, Set[UserRole]] = {
    CustodyState.SUBMITTED.value: {UserRole.COLLECTOR, UserRole.SUPER_ADMIN},
    CustodyState.PICKUP_ASSIGNED.value: {
        UserRole.LOGISTICS,
        UserRole.SUPER_ADMIN,
        UserRole.CORPORATE,
        UserRole.COLLECTOR,
    },
    CustodyState.PICKED_UP.value: {UserRole.LOGISTICS, UserRole.SUPER_ADMIN},
    CustodyState.IN_TRANSIT.value: {UserRole.LOGISTICS, UserRole.SUPER_ADMIN},
    CustodyState.DELIVERED.value: {UserRole.LOGISTICS, UserRole.SUPER_ADMIN},
    CustodyState.RECEIVED.value: {UserRole.RECYCLER, UserRole.UPCYCLER, UserRole.SUPER_ADMIN},
    CustodyState.VERIFIED.value: {UserRole.VERIFIER, UserRole.AUDITOR, UserRole.SUPER_ADMIN},
    CustodyState.PROCESSED.value: {UserRole.RECYCLER, UserRole.UPCYCLER, UserRole.SUPER_ADMIN},
    CustodyState.REJECTED.value: {
        UserRole.VERIFIER,
        UserRole.AUDITOR,
        UserRole.CORPORATE,
        UserRole.RECYCLER,
        UserRole.SUPER_ADMIN,
    },
}


class ChainOfCustodyService(BaseService):
    """Domain service governing material chain-of-custody milestones and immutability."""

    def __init__(
        self,
        settings: Settings,
        custody_repo: ChainOfCustodyRepository,
        recovery_repo: RecoveryRepository,
        program_repo: ProgramRepository,
        program_partner_repo: ProgramPartnerRepository,
        audit_repo: AuditRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.custody_repo = custody_repo
        self.recovery_repo = recovery_repo
        self.program_repo = program_repo
        self.program_partner_repo = program_partner_repo
        self.audit_repo = audit_repo

    async def transition_custody(
        self,
        recovery_id: uuid.UUID,
        data: CustodyTransitionRequest,
        actor: User,
    ) -> CustodyTimelineResponse:
        """Advance a recovery event along the circular chain-of-custody."""
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException(f"Recovery event '{recovery_id}' does not exist.")

        # 1. Authorize actor affiliation with program
        await self._assert_actor_custody_access(recovery, actor)

        # 2. Check current state and valid transitions
        current_state = recovery.custody_status or CustodyState.CREATED.value
        target_state = data.new_state.value

        allowed_next = VALID_TRANSITIONS.get(current_state, set())
        if target_state not in allowed_next:
            raise BadRequestException(
                f"Invalid chain-of-custody transition from '{current_state}' to '{target_state}'. "
                f"Valid next states: {sorted(list(allowed_next)) or 'None (Terminal state)'}"
            )

        # 3. Check role permission for target state
        if actor.role != UserRole.SUPER_ADMIN:
            allowed_roles = ROLE_STATE_PERMISSIONS.get(target_state, set())
            if actor.role not in allowed_roles:
                raise ForbiddenException(
                    f"Role '{actor.role.value}' is not authorized to transition custody to '{target_state}'."
                )

        # 4. Record immutable chain-of-custody event
        custody_event = ChainOfCustodyEvent(
            resource=recovery.recovery_id,
            resource_type="RECOVERY_EVENT",
            resource_id=recovery.id,
            previous_state=current_state,
            new_state=target_state,
            actor_id=actor.id,
            actor_role=actor.role.value,
            timestamp=datetime.now(timezone.utc),
            event_metadata=data.metadata,
            notes=data.notes.strip() if data.notes else None,
        )
        await self.custody_repo.record_event(custody_event)

        # 5. Update recovery event custody_status
        recovery.custody_status = target_state
        if target_state == CustodyState.SUBMITTED.value and recovery.status == RecoveryStatus.DRAFT:
            recovery.status = RecoveryStatus.SUBMITTED
            await self.program_repo.update_collected_weight(recovery.program_id, recovery.weight_kg)

        await self.recovery_repo.session.flush()

        # 6. Audit logging
        await self.audit_repo.record(
            action="CUSTODY_TRANSITION",
            resource=f"recovery:{recovery.recovery_id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "recovery_id": str(recovery.id),
                "human_id": recovery.recovery_id,
                "from_state": current_state,
                "to_state": target_state,
            },
        )

        self.logger.info(
            f"Chain of Custody for {recovery.recovery_id} transitioned: {current_state} -> {target_state} by {actor.email} ({actor.role.value})"
        )

        return await self.get_custody_timeline(recovery.id, actor)

    async def get_custody_timeline(
        self, recovery_id: uuid.UUID, requester: User
    ) -> CustodyTimelineResponse:
        """Retrieve full chronological immutable history of chain-of-custody milestones."""
        recovery = await self.recovery_repo.get_by_id(recovery_id)
        if not recovery:
            raise NotFoundException("Recovery event not found.")

        await self._assert_actor_custody_access(recovery, requester)

        events = await self.custody_repo.list_for_resource(recovery.id)
        event_responses = [
            CustodyEventResponse(
                id=e.id,
                resource=e.resource,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                previous_state=e.previous_state,
                new_state=e.new_state,
                actor_id=e.actor_id,
                actor_role=e.actor_role,
                actor_name=e.actor.full_name if e.actor else None,
                timestamp=e.timestamp,
                event_metadata=e.event_metadata,
                notes=e.notes,
            )
            for e in events
        ]

        return CustodyTimelineResponse(
            resource=recovery.recovery_id,
            resource_id=recovery.id,
            current_state=recovery.custody_status or CustodyState.CREATED.value,
            events=event_responses,
        )

    # --------------------------------------------------------------------------
    # Access Enforcement
    # --------------------------------------------------------------------------

    async def _assert_actor_custody_access(
        self, recovery: RecoveryEvent, user: User
    ) -> None:
        """Verify user is affiliated with the recovery event, program, or assigned partner org."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if recovery.collector_id == user.id:
            return

        if user.organization_id and user.organization_id == recovery.collector_organization_id:
            return

        program = await self.program_repo.get_by_id(recovery.program_id)
        if program and user.organization_id and user.organization_id == program.organization_id:
            return

        if user.organization_id and await self.program_partner_repo.is_partner_assigned(
            recovery.program_id, user.organization_id
        ):
            return

        raise ForbiddenException("Access denied: You do not have permission to access the chain of custody for this recovery.")
