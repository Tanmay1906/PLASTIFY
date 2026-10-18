"""PLASTIFY Plastic Collection and Recovery Engine Service.

Enforces server-side validations, generates immutable Recovery IDs,
records state transition audit logs, and coordinates recovery lifecycles.
"""

from datetime import datetime, timezone
from typing import List, Optional, Union
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.program import Program, ProgramStatus
from app.models.recovery import (
    RecoveryEvent,
    RecoveryEventHistory,
    RecoveryStatus,
)
from app.models.user import User, UserRole
from app.repositories.organization import OrgMemberRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.repositories.recovery import (
    RecoveryHistoryRepository,
    RecoveryRepository,
)
from app.schemas.recovery import (
    RecoveryCreateRequest,
    RecoveryHistoryResponse,
    RecoveryResponse,
    RecoverySubmitRequest,
    RecoveryUpdateRequest,
)
from app.services.base import BaseService


class RecoveryService(BaseService):
    """Core domain service managing post-consumer plastic recovery events."""

    def __init__(
        self,
        settings: Settings,
        recovery_repo: RecoveryRepository,
        history_repo: RecoveryHistoryRepository,
        program_repo: ProgramRepository,
        program_partner_repo: ProgramPartnerRepository,
        member_repo: OrgMemberRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.recovery_repo = recovery_repo
        self.history_repo = history_repo
        self.program_repo = program_repo
        self.program_partner_repo = program_partner_repo
        self.member_repo = member_repo

    async def create_recovery(
        self, data: RecoveryCreateRequest, collector: User
    ) -> RecoveryResponse:
        """Create a new plastic Recovery Event in DRAFT status with immutable Recovery ID."""
        # 1. Validation: Collector role check
        if collector.role not in [UserRole.COLLECTOR, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Only authorized COLLECTOR accounts can record recovery events.")

        # 2. Validation: Collector must belong to an organization
        if not collector.organization_id:
            raise BadRequestException("Collector must be affiliated with an authorized organization.")

        # 3. Validation: Program must exist and be active
        program = await self.program_repo.get_by_id(data.program_id)
        if not program:
            raise NotFoundException(f"Program '{data.program_id}' does not exist.")

        if program.status != ProgramStatus.ACTIVE:
            raise BadRequestException(
                f"Program '{program.name}' is not ACTIVE (current status: {program.status.value}). Cannot log recoveries."
            )

        # 4. Validation: Collector's organization must be assigned to the program
        if collector.role != UserRole.SUPER_ADMIN:
            is_assigned = await self.program_partner_repo.is_partner_assigned(
                program.id, collector.organization_id
            )
            if not is_assigned:
                raise ForbiddenException(
                    "Collector organization is not an assigned operational partner for this program."
                )

        # 5. Validation: Material type must be allowed by program
        clean_material = data.material_type.strip().upper()
        allowed = [m.upper() for m in program.allowed_material_types]
        if clean_material not in allowed:
            raise BadRequestException(
                f"Material '{clean_material}' is not permitted by program '{program.name}'. Allowed materials: {allowed}"
            )

        # 6. Validation: Positive weight
        if data.weight_kg <= 0:
            raise BadRequestException("Weight must be strictly greater than zero kilograms.")

        # 7. Validation: Valid timestamp
        collection_time = data.collected_at or datetime.now(timezone.utc)
        if collection_time > datetime.now(timezone.utc):
            raise BadRequestException("Collection timestamp cannot be in the future.")

        # 8. Generate immutable official human-readable Recovery ID
        recovery_year = collection_time.year
        recovery_id = await self.recovery_repo.generate_next_recovery_id(
            region=program.region, year=recovery_year
        )

        # 9. Create Recovery Event
        event = RecoveryEvent(
            recovery_id=recovery_id,
            program_id=program.id,
            collector_id=collector.id,
            collector_organization_id=collector.organization_id,
            material_type=clean_material,
            weight_kg=round(data.weight_kg, 3),
            collection_location=data.collection_location.strip(),
            collection_coordinates=data.collection_coordinates,
            collected_at=collection_time,
            notes=data.notes.strip() if data.notes else None,
            status=RecoveryStatus.DRAFT,
        )
        created_event = await self.recovery_repo.create(event)

        # 10. Record immutable state history
        await self.history_repo.record_transition(
            recovery_event_id=created_event.id,
            from_status=None,
            to_status=RecoveryStatus.DRAFT.value,
            actor_id=collector.id,
            actor_role=collector.role.value,
            notes="Initial collection draft created",
            event_metadata={
                "weight_kg": created_event.weight_kg,
                "material_type": created_event.material_type,
            },
        )

        self.logger.info(
            f"Recovery Event created: {created_event.recovery_id} ({created_event.weight_kg}kg {created_event.material_type}) by {collector.email}"
        )
        return await self._build_recovery_response(created_event)

    async def update_draft_recovery(
        self,
        event_id: uuid.UUID,
        data: RecoveryUpdateRequest,
        collector: User,
    ) -> RecoveryResponse:
        """Update an existing unsubmitted draft recovery event."""
        event = await self.recovery_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException("Recovery event not found.")

        # Only DRAFT recoveries can be edited
        if event.status != RecoveryStatus.DRAFT:
            raise BadRequestException(
                f"Cannot modify recovery event in '{event.status.value}' status. Only DRAFT events can be modified."
            )

        # Only the creating collector or Super Admin can edit
        if collector.role != UserRole.SUPER_ADMIN and event.collector_id != collector.id:
            raise ForbiddenException("Access denied: You can only edit your own draft recovery events.")

        update_dict = data.model_dump(exclude_unset=True)

        if "material_type" in update_dict:
            program = await self.program_repo.get_by_id(event.program_id)
            clean_material = update_dict["material_type"].strip().upper()
            allowed = [m.upper() for m in program.allowed_material_types]
            if clean_material not in allowed:
                raise BadRequestException(
                    f"Material '{clean_material}' is not permitted by program. Allowed: {allowed}"
                )
            event.material_type = clean_material

        if "weight_kg" in update_dict:
            if update_dict["weight_kg"] <= 0:
                raise BadRequestException("Weight must be strictly positive.")
            event.weight_kg = round(update_dict["weight_kg"], 3)

        if "collection_location" in update_dict:
            event.collection_location = update_dict["collection_location"].strip()

        if "collection_coordinates" in update_dict:
            event.collection_coordinates = update_dict["collection_coordinates"]

        if "collected_at" in update_dict:
            event.collected_at = update_dict["collected_at"]

        if "notes" in update_dict:
            event.notes = update_dict["notes"]

        await self.recovery_repo.session.flush()
        self.logger.info(f"Recovery draft '{event.recovery_id}' updated by {collector.email}")
        return await self._build_recovery_response(event)

    async def submit_recovery(
        self,
        event_id: uuid.UUID,
        data: RecoverySubmitRequest,
        collector: User,
    ) -> RecoveryResponse:
        """Submit a draft recovery event, locking it and updating program progress."""
        event = await self.recovery_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException("Recovery event not found.")

        if event.status != RecoveryStatus.DRAFT:
            raise BadRequestException(
                f"Recovery event is already in '{event.status.value}' status. Only DRAFT events can be submitted."
            )

        # Only creating collector or Super Admin can submit
        if collector.role != UserRole.SUPER_ADMIN and event.collector_id != collector.id:
            raise ForbiddenException("Access denied: You can only submit your own recovery events.")

        # Transition status
        from_status = event.status.value
        event.status = RecoveryStatus.SUBMITTED

        # Update program's total collected weight
        await self.program_repo.update_collected_weight(event.program_id, event.weight_kg)

        await self.recovery_repo.session.flush()

        # Record immutable transition history
        await self.history_repo.record_transition(
            recovery_event_id=event.id,
            from_status=from_status,
            to_status=RecoveryStatus.SUBMITTED.value,
            actor_id=collector.id,
            actor_role=collector.role.value,
            notes=data.notes or "Official submission by collector",
            event_metadata={"weight_kg": event.weight_kg, "material_type": event.material_type},
        )

        self.logger.info(
            f"Recovery Event {event.recovery_id} SUBMITTED ({event.weight_kg}kg) by {collector.email}"
        )
        return await self._build_recovery_response(event)

    async def get_recovery(
        self, identifier: Union[uuid.UUID, str], requester: User
    ) -> RecoveryResponse:
        """Retrieve recovery event by internal UUID or human-readable recovery ID."""
        event: Optional[RecoveryEvent] = None
        if isinstance(identifier, uuid.UUID):
            event = await self.recovery_repo.get_with_details(identifier)
        else:
            try:
                parsed_uuid = uuid.UUID(identifier)
                event = await self.recovery_repo.get_with_details(parsed_uuid)
            except ValueError:
                event = await self.recovery_repo.get_by_recovery_id(identifier)

        if not event:
            raise NotFoundException("Recovery event not found.")

        # Tenant & access validation
        await self._assert_recovery_access(event, requester)

        return await self._build_recovery_response(event)

    async def list_collector_recoveries(
        self,
        collector_id: Optional[uuid.UUID],
        requester: User,
        skip: int = 0,
        limit: int = 50,
    ) -> List[RecoveryResponse]:
        """List recovery events logged by a collector or their organization."""
        target_collector_id = collector_id or requester.id

        # Non-superadmin collectors can only view recoveries from their own organization
        if requester.role != UserRole.SUPER_ADMIN:
            if requester.organization_id is None:
                raise ForbiddenException("User must belong to an organization.")
            # Fetch for their organization
            events = await self.recovery_repo.list_by_collector_organization(
                requester.organization_id, skip=skip, limit=limit
            )
        else:
            events = await self.recovery_repo.list_by_collector(
                target_collector_id, skip=skip, limit=limit
            )

        return [await self._build_recovery_response(e) for e in events]

    async def list_program_recoveries(
        self, program_id: uuid.UUID, requester: User, skip: int = 0, limit: int = 50
    ) -> List[RecoveryResponse]:
        """List all recovery events logged under a specific corporate program."""
        program = await self.program_repo.get_by_id(program_id)
        if not program:
            raise NotFoundException("Program not found.")

        # Access check: Super Admin, corporate owner, or assigned partner
        is_super = requester.role == UserRole.SUPER_ADMIN
        is_owner = requester.organization_id == program.organization_id
        is_partner = (
            requester.organization_id is not None
            and await self.program_partner_repo.is_partner_assigned(
                program.id, requester.organization_id
            )
        )

        if not (is_super or is_owner or is_partner):
            raise ForbiddenException("Access denied: You do not have permission to view recoveries for this program.")

        events = await self.recovery_repo.list_by_program(program_id, skip=skip, limit=limit)
        return [await self._build_recovery_response(e) for e in events]

    async def get_recovery_history(
        self, event_id: uuid.UUID, requester: User
    ) -> List[RecoveryHistoryResponse]:
        """Fetch immutable history audit trail for an event."""
        event = await self.recovery_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException("Recovery event not found.")
        await self._assert_recovery_access(event, requester)
        records = await self.history_repo.list_for_event(event.id)
        return [
            RecoveryHistoryResponse(
                id=h.id,
                recovery_event_id=h.recovery_event_id,
                from_status=h.from_status,
                to_status=h.to_status,
                actor_id=h.actor_id,
                actor_role=h.actor_role,
                notes=h.notes,
                event_metadata=h.event_metadata,
                created_at=h.created_at,
            )
            for h in records
        ]

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    async def _assert_recovery_access(self, event: RecoveryEvent, user: User) -> None:
        """Enforce that requester has legitimate access to the recovery event."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        # 1. Collector who created it
        if event.collector_id == user.id:
            return

        # 2. Collector's organization member
        if user.organization_id == event.collector_organization_id:
            return

        # 3. Corporate owner of the program
        program = await self.program_repo.get_by_id(event.program_id)
        if program and user.organization_id == program.organization_id:
            return

        raise ForbiddenException("Access denied: You do not have permission to access this recovery event.")

    async def _build_recovery_response(self, event: RecoveryEvent) -> RecoveryResponse:
        """Assemble full recovery response including immutable transition history."""
        # Load history if not already present
        history_records = await self.history_repo.list_for_event(event.id)
        history_responses = [
            RecoveryHistoryResponse(
                id=h.id,
                recovery_event_id=h.recovery_event_id,
                from_status=h.from_status,
                to_status=h.to_status,
                actor_id=h.actor_id,
                actor_role=h.actor_role,
                notes=h.notes,
                event_metadata=h.event_metadata,
                created_at=h.created_at,
            )
            for h in history_records
        ]

        program_name = event.program.name if event.program else None
        collector_name = event.collector.full_name if event.collector else None
        org_name = (
            event.collector_organization.name if event.collector_organization else None
        )

        return RecoveryResponse(
            id=event.id,
            recovery_id=event.recovery_id,
            program_id=event.program_id,
            program_name=program_name,
            collector_id=event.collector_id,
            collector_name=collector_name,
            collector_organization_id=event.collector_organization_id,
            collector_organization_name=org_name,
            material_type=event.material_type,
            weight_kg=event.weight_kg,
            collection_location=event.collection_location,
            collection_coordinates=event.collection_coordinates,
            collected_at=event.collected_at,
            notes=event.notes,
            status=event.status,
            custody_status=event.custody_status,
            created_at=event.created_at,
            updated_at=event.updated_at,
            history=history_responses,
        )
