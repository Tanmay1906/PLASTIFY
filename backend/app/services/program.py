"""PLASTIFY Corporate Plastic Recovery Program Service.

Coordinates program creation, lifecycle transitions, and operational partner assignments.
"""

from typing import List
import uuid

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.organization import OrgMemberRole
from app.models.program import Program, ProgramPartner, ProgramStatus
from app.models.user import User, UserRole
from app.repositories.organization import OrganizationRepository, OrgMemberRepository
from app.repositories.program import ProgramPartnerRepository, ProgramRepository
from app.schemas.program import (
    ProgramCreateRequest,
    ProgramPartnerAssignRequest,
    ProgramPartnerResponse,
    ProgramResponse,
    ProgramUpdateRequest,
)
from app.services.base import BaseService


class ProgramService(BaseService):
    """Business service governing plastic recovery programs and partner networks."""

    def __init__(
        self,
        settings: Settings,
        program_repo: ProgramRepository,
        partner_repo: ProgramPartnerRepository,
        org_repo: OrganizationRepository,
        member_repo: OrgMemberRepository,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.program_repo = program_repo
        self.partner_repo = partner_repo
        self.org_repo = org_repo
        self.member_repo = member_repo

    async def create_program(
        self, data: ProgramCreateRequest, creator: User
    ) -> ProgramResponse:
        """Create a new corporate plastic recovery program."""
        # 1. Authorization: Must be CORPORATE role or SUPER_ADMIN
        if creator.role not in [UserRole.CORPORATE, UserRole.SUPER_ADMIN]:
            raise ForbiddenException("Only CORPORATE organizations can launch recovery programs.")

        # 2. Validation: Creator must belong to an organization
        if not creator.organization_id:
            raise BadRequestException("User must be affiliated with an organization to create a program.")

        # 3. Create program
        program = Program(
            organization_id=creator.organization_id,
            name=data.name.strip(),
            description=data.description.strip() if data.description else None,
            region=data.region.strip().upper(),
            target_kg=data.target_kg,
            collected_kg=0.0,
            allowed_material_types=[m.strip().upper() for m in data.allowed_material_types],
            start_date=data.start_date,
            end_date=data.end_date,
            status=data.status or ProgramStatus.DRAFT,
        )
        created = await self.program_repo.create(program)

        self.logger.info(
            f"Program created: '{created.name}' [{created.id}] by {creator.email} (Org: {creator.organization_id})"
        )
        return self._build_program_response(created)

    async def get_program(
        self, program_id: uuid.UUID, requester: User
    ) -> ProgramResponse:
        """Fetch program details with tenant access verification."""
        program = await self.program_repo.get_with_organization(program_id)
        if not program:
            raise NotFoundException(f"Program '{program_id}' not found.")

        # Access check: Super Admin, owning organization, assigned partner, or public active program
        is_owner = requester.organization_id == program.organization_id
        is_super = requester.role == UserRole.SUPER_ADMIN
        is_partner = (
            requester.organization_id is not None
            and await self.partner_repo.is_partner_assigned(program.id, requester.organization_id)
        )
        is_active = program.status == ProgramStatus.ACTIVE

        if not (is_owner or is_super or is_partner or is_active):
            raise ForbiddenException("Access denied: You do not have permission to view this program.")

        return self._build_program_response(program)

    async def update_program(
        self, program_id: uuid.UUID, data: ProgramUpdateRequest, requester: User
    ) -> ProgramResponse:
        """Update program metadata or lifecycle status."""
        program = await self.program_repo.get_with_organization(program_id)
        if not program:
            raise NotFoundException(f"Program '{program_id}' not found.")

        # Authorization: only program owner (or super admin) can modify
        await self._assert_program_owner(program, requester)

        update_dict = data.model_dump(exclude_unset=True)
        if "name" in update_dict:
            program.name = update_dict["name"].strip()
        if "description" in update_dict:
            program.description = update_dict["description"]
        if "region" in update_dict:
            program.region = update_dict["region"].strip().upper()
        if "target_kg" in update_dict:
            program.target_kg = update_dict["target_kg"]
        if "allowed_material_types" in update_dict:
            program.allowed_material_types = [
                m.strip().upper() for m in update_dict["allowed_material_types"]
            ]
        if "start_date" in update_dict:
            program.start_date = update_dict["start_date"]
        if "end_date" in update_dict:
            program.end_date = update_dict["end_date"]
        if "status" in update_dict:
            program.status = update_dict["status"]

        await self.program_repo.session.flush()
        self.logger.info(f"Program '{program.name}' updated by {requester.email}")
        return self._build_program_response(program)

    async def list_programs(
        self, requester: User, skip: int = 0, limit: int = 50
    ) -> List[ProgramResponse]:
        """List programs tailored to the requesting user's role and affiliation."""
        if requester.role == UserRole.SUPER_ADMIN:
            programs = await self.program_repo.list(skip=skip, limit=limit)
            return [self._build_program_response(p) for p in programs]

        if requester.role == UserRole.CORPORATE and requester.organization_id:
            programs = await self.program_repo.list_by_organization(
                requester.organization_id, skip=skip, limit=limit
            )
            return [self._build_program_response(p) for p in programs]

        # For Collector or other operational partners: return assigned programs or active programs
        if requester.organization_id:
            assignments = await self.partner_repo.list_by_partner_org(requester.organization_id)
            program_ids = [a.program_id for a in assignments]
            assigned_programs = []
            for pid in program_ids:
                p = await self.program_repo.get_by_id(pid)
                if p:
                    assigned_programs.append(self._build_program_response(p))
            if assigned_programs:
                return assigned_programs

        # Default fallback: view active programs
        active = await self.program_repo.list_active(skip=skip, limit=limit)
        return [self._build_program_response(p) for p in active]

    # --------------------------------------------------------------------------
    # Operational Partner Management
    # --------------------------------------------------------------------------

    async def assign_partner(
        self,
        program_id: uuid.UUID,
        data: ProgramPartnerAssignRequest,
        requester: User,
    ) -> ProgramPartnerResponse:
        """Assign an operational partner (e.g. Collector) to the program."""
        program = await self.program_repo.get_by_id(program_id)
        if not program:
            raise NotFoundException("Program not found.")

        await self._assert_program_owner(program, requester)

        target_org = await self.org_repo.get_by_id(data.organization_id)
        if not target_org or not target_org.is_active:
            raise NotFoundException("Target partner organization does not exist or is inactive.")

        existing = await self.partner_repo.get_assignment(program_id, data.organization_id)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                await self.partner_repo.session.flush()
                return ProgramPartnerResponse(
                    id=existing.id,
                    program_id=existing.program_id,
                    organization_id=existing.organization_id,
                    organization_name=target_org.name,
                    assigned_role=existing.assigned_role,
                    is_active=True,
                    created_at=existing.created_at,
                )
            raise ConflictException("Organization is already assigned to this program.")

        partner = ProgramPartner(
            program_id=program_id,
            organization_id=data.organization_id,
            assigned_role=data.assigned_role.strip().upper(),
            is_active=True,
        )
        created = await self.partner_repo.create(partner)

        self.logger.info(
            f"Assigned partner {target_org.name} [{target_org.id}] to program '{program.name}'"
        )
        return ProgramPartnerResponse(
            id=created.id,
            program_id=created.program_id,
            organization_id=created.organization_id,
            organization_name=target_org.name,
            assigned_role=created.assigned_role,
            is_active=created.is_active,
            created_at=created.created_at,
        )

    async def list_partners(
        self, program_id: uuid.UUID, requester: User
    ) -> List[ProgramPartnerResponse]:
        """List assigned operational partners for a program."""
        program = await self.program_repo.get_by_id(program_id)
        if not program:
            raise NotFoundException("Program not found.")

        partners = await self.partner_repo.list_by_program(program_id)
        results = []
        for p in partners:
            results.append(
                ProgramPartnerResponse(
                    id=p.id,
                    program_id=p.program_id,
                    organization_id=p.organization_id,
                    organization_name=p.organization.name if p.organization else None,
                    assigned_role=p.assigned_role,
                    is_active=p.is_active,
                    created_at=p.created_at,
                )
            )
        return results

    async def remove_partner(
        self, program_id: uuid.UUID, partner_org_id: uuid.UUID, requester: User
    ) -> None:
        """Deactivate or remove an operational partner from the program."""
        program = await self.program_repo.get_by_id(program_id)
        if not program:
            raise NotFoundException("Program not found.")

        await self._assert_program_owner(program, requester)

        assignment = await self.partner_repo.get_assignment(program_id, partner_org_id)
        if not assignment:
            raise NotFoundException("Partner assignment not found.")

        await self.partner_repo.delete(assignment)
        self.logger.info(f"Removed partner {partner_org_id} from program {program_id}")

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    async def _assert_program_owner(self, program: Program, user: User) -> None:
        """Enforce that requester is the corporate owner or Super Admin."""
        if user.role == UserRole.SUPER_ADMIN:
            return

        if user.organization_id != program.organization_id:
            raise ForbiddenException("Access denied: You do not own this program.")

        is_admin = await self.member_repo.is_org_admin(program.organization_id, user.id)
        if not is_admin:
            raise ForbiddenException("Access denied: Organization admin role required.")

    def _build_program_response(self, program: Program) -> ProgramResponse:
        """Helper to compute progress and construct ProgramResponse."""
        progress = 0.0
        if program.target_kg > 0:
            progress = round((program.collected_kg / program.target_kg) * 100, 2)

        return ProgramResponse(
            id=program.id,
            organization_id=program.organization_id,
            organization_name=program.organization.name if program.organization else None,
            name=program.name,
            description=program.description,
            region=program.region,
            target_kg=program.target_kg,
            collected_kg=program.collected_kg,
            progress_percent=progress,
            allowed_material_types=program.allowed_material_types,
            start_date=program.start_date,
            end_date=program.end_date,
            status=program.status,
            created_at=program.created_at,
            updated_at=program.updated_at,
        )
