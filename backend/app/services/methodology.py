"""PLASTIFY Methodology Engine Service.

Manages accounting standard protocols and immutable versioned calculation parameters.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import List, Optional
import uuid

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.impact import ImpactOutcomeType, Methodology, MethodologyVersion
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.impact import MethodologyRepository
from app.schemas.impact import (
    MethodologyCreateRequest,
    MethodologyResponse,
    MethodologyVersionCreateRequest,
    MethodologyVersionResponse,
)

logger = logging.getLogger("plastify.services.methodology")


class MethodologyService:
    """Business service governing accounting methodologies and immutable version tags."""

    def __init__(
        self,
        methodology_repo: MethodologyRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.methodology_repo = methodology_repo
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. Methodology Lifecycle
    # --------------------------------------------------------------------------

    async def create_methodology(
        self, data: MethodologyCreateRequest, actor: User
    ) -> MethodologyResponse:
        """Register a new carbon/plastic crediting methodology standard."""
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            raise ForbiddenException("Only SUPER_ADMIN or AUDITOR roles can register new accounting methodologies.")

        clean_code = data.code.strip().upper()
        existing = await self.methodology_repo.get_by_code(clean_code)
        if existing:
            raise ConflictException(f"Methodology with code '{clean_code}' already exists.")

        methodology = Methodology(
            code=clean_code,
            name=data.name.strip(),
            description=data.description.strip(),
            standard_name=data.standard_name.strip(),
            is_standard_recognized=data.is_standard_recognized,
            registry_name=data.registry_name.strip() if data.registry_name else None,
            is_active=True,
        )
        created = await self.methodology_repo.create(methodology)

        await self.audit_repo.record(
            action="METHODOLOGY_CREATED",
            resource=f"methodology:{created.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={"code": created.code, "name": created.name},
        )

        logger.info(f"Methodology created: {created.code} ({created.name}) by {actor.email}")
        return self._build_methodology_response(created)

    async def create_version(
        self, methodology_id: uuid.UUID, data: MethodologyVersionCreateRequest, actor: User
    ) -> MethodologyVersionResponse:
        """Create an immutable calculation version under a methodology."""
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.AUDITOR]:
            raise ForbiddenException("Only SUPER_ADMIN or AUDITOR roles can register methodology versions.")

        methodology = await self.methodology_repo.get_by_id(methodology_id)
        if not methodology:
            raise NotFoundException("Methodology not found.")

        clean_tag = data.version_tag.strip()
        existing_version = await self.methodology_repo.get_version_by_tag(methodology.id, clean_tag)
        if existing_version:
            raise ConflictException(f"Version '{clean_tag}' already exists for methodology '{methodology.code}'.")

        # Conversion factor check
        if data.credit_conversion_factor <= Decimal("0.000000"):
            raise BadRequestException("Credit conversion factor must be strictly positive.")

        # Total discounts must not exceed 100%
        total_deductions = data.additionality_discount + data.baseline_discount + data.leakage_deduction
        if total_deductions >= Decimal("1.0000"):
            raise BadRequestException(
                f"Combined deductions ({total_deductions}) cannot exceed or equal 1.0 (100%)."
            )

        formula = data.calculation_formula or "NET = GROSS_KG * CONVERSION_FACTOR * (1 - (ADDITIONALITY + BASELINE + LEAKAGE))"
        disclaimer = data.disclaimer or (
            "DISCLAIMER: PLASTIFY assessments provide auditable ecological accounting. "
            "Unless explicitly certified by a recognized sovereign or independent standard body, "
            "calculations represent private environmental reporting rather than sovereign credits."
        )

        now_utc = datetime.now(timezone.utc)
        eff_from = data.effective_from or datetime(now_utc.year, 1, 1, tzinfo=timezone.utc)

        version = MethodologyVersion(
            methodology_id=methodology.id,
            version_tag=clean_tag,
            activity_type=data.activity_type,
            effective_from=eff_from,
            effective_to=data.effective_to,
            is_immutable=True,
            eligible_materials=[m.strip().upper() for m in data.eligible_materials],
            credit_conversion_factor=data.credit_conversion_factor,
            credit_unit_name=data.credit_unit_name.strip().upper(),
            additionality_discount=data.additionality_discount,
            baseline_discount=data.baseline_discount,
            leakage_deduction=data.leakage_deduction,
            required_evidence_types=[e.strip().upper() for e in data.required_evidence_types],
            requires_independent_verification=data.requires_independent_verification,
            calculation_formula=formula,
            disclaimer=disclaimer,
            parameters=data.parameters or {},
        )
        created_version = await self.methodology_repo.create_version(version)

        await self.audit_repo.record(
            action="METHODOLOGY_VERSION_CREATED",
            resource=f"methodology_version:{created_version.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role.value,
            metadata={
                "methodology_code": methodology.code,
                "version_tag": created_version.version_tag,
                "conversion_factor": float(created_version.credit_conversion_factor),
            },
        )

        logger.info(f"Methodology version created: {methodology.code} v{created_version.version_tag} by {actor.email}")
        return self._build_version_response(created_version)

    # --------------------------------------------------------------------------
    # 2. Retrieval & Listing
    # --------------------------------------------------------------------------

    async def list_methodologies(self) -> List[MethodologyResponse]:
        """List all active methodologies."""
        items = await self.methodology_repo.list_active()
        return [self._build_methodology_response(m) for m in items]

    async def get_methodology_by_id(self, methodology_id: uuid.UUID) -> MethodologyResponse:
        """Fetch methodology by UUID."""
        item = await self.methodology_repo.get_by_id(methodology_id)
        if not item:
            raise NotFoundException("Methodology not found.")
        return self._build_methodology_response(item)

    async def get_version_by_id(self, version_id: uuid.UUID) -> MethodologyVersionResponse:
        """Fetch methodology version by UUID."""
        version = await self.methodology_repo.get_version_by_id(version_id)
        if not version:
            raise NotFoundException("Methodology version not found.")
        return self._build_version_response(version)

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _build_version_response(self, v: MethodologyVersion) -> MethodologyVersionResponse:
        return MethodologyVersionResponse(
            id=v.id,
            methodology_id=v.methodology_id,
            version_tag=v.version_tag,
            activity_type=v.activity_type,
            effective_from=v.effective_from,
            effective_to=v.effective_to,
            is_immutable=v.is_immutable,
            eligible_materials=v.eligible_materials,
            credit_conversion_factor=v.credit_conversion_factor,
            credit_unit_name=v.credit_unit_name,
            additionality_discount=v.additionality_discount,
            baseline_discount=v.baseline_discount,
            leakage_deduction=v.leakage_deduction,
            required_evidence_types=v.required_evidence_types,
            requires_independent_verification=v.requires_independent_verification,
            calculation_formula=v.calculation_formula,
            disclaimer=v.disclaimer,
            parameters=v.parameters,
            created_at=v.created_at,
        )

    def _build_methodology_response(self, m: Methodology) -> MethodologyResponse:
        versions = [self._build_version_response(v) for v in m.versions]
        return MethodologyResponse(
            id=m.id,
            code=m.code,
            name=m.name,
            description=m.description,
            standard_name=m.standard_name,
            is_standard_recognized=m.is_standard_recognized,
            registry_name=m.registry_name,
            is_active=m.is_active,
            created_at=m.created_at,
            updated_at=m.updated_at,
            versions=versions,
        )
