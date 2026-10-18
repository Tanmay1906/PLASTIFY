"""PLASTIFY Credit Eligibility Assessment Service.

Performs deterministic, reproducible credit evaluations of verified physical impact records
against immutable methodology specifications.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.impact import (
    AssessmentStatus,
    EligibilityAssessment,
    ImpactRecord,
    ImpactStatus,
    MethodologyVersion,
)
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.impact import AssessmentRepository, ImpactRepository, MethodologyRepository
from app.schemas.impact import (
    EligibilityAssessmentCreateRequest,
    EligibilityAssessmentResponse,
)

logger = logging.getLogger("plastify.services.eligibility")


class EligibilityService:
    """Business service governing deterministic credit eligibility assessments."""

    def __init__(
        self,
        assessment_repo: AssessmentRepository,
        impact_repo: ImpactRepository,
        methodology_repo: MethodologyRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.assessment_repo = assessment_repo
        self.impact_repo = impact_repo
        self.methodology_repo = methodology_repo
        self.audit_repo = audit_repo

    # --------------------------------------------------------------------------
    # 1. Run Eligibility Assessment
    # --------------------------------------------------------------------------

    async def assess_impact_eligibility(
        self, data: EligibilityAssessmentCreateRequest, assessor: User
    ) -> EligibilityAssessmentResponse:
        """Run a reproducible eligibility evaluation for an impact record against a methodology version."""
        impact = await self.impact_repo.get_by_id(data.impact_record_id)
        if not impact:
            raise NotFoundException("Impact record not found.")

        # Check tenant boundary
        if assessor.role not in [UserRole.SUPER_ADMIN, UserRole.VERIFIER, UserRole.AUDITOR]:
            if impact.organization_id != assessor.organization_id:
                raise ForbiddenException("Access denied: You cannot assess impact records of another organization.")

        version = await self.methodology_repo.get_version_by_id(data.methodology_version_id)
        if not version:
            raise NotFoundException("Methodology version not found.")

        # Evaluate Checklist Gates
        checklist: Dict[str, Any] = {}
        reasons: List[str] = []
        is_eligible = True
        requires_review = False

        # Gate 1: Activity Outcome Compatibility
        activity_match = (impact.outcome_type == version.activity_type)
        checklist["activity_outcome_match"] = {
            "passed": activity_match,
            "impact_outcome": impact.outcome_type.value,
            "methodology_activity": version.activity_type.value,
        }
        if not activity_match:
            is_eligible = False
            reasons.append(
                f"Activity outcome mismatch: Impact record is '{impact.outcome_type.value}', "
                f"but methodology requires '{version.activity_type.value}'."
            )

        # Gate 2: Impact Status
        status_valid = (impact.status == ImpactStatus.VERIFIED)
        checklist["impact_status_verified"] = {
            "passed": status_valid,
            "status": impact.status.value,
        }
        if not status_valid:
            is_eligible = False
            reasons.append(f"Impact record status '{impact.status.value}' is not VERIFIED.")

        # Gate 3: Polymer / Material Eligibility
        clean_mat = impact.material_type.strip().upper()
        mat_allowed = [m.strip().upper() for m in version.eligible_materials]
        mat_eligible = (clean_mat in mat_allowed)
        checklist["material_type_eligible"] = {
            "passed": mat_eligible,
            "material_type": clean_mat,
            "eligible_materials": mat_allowed,
        }
        if not mat_eligible:
            is_eligible = False
            reasons.append(f"Material '{clean_mat}' is not permitted by methodology. Eligible: {mat_allowed}")

        # Gate 4: Available Unallocated Quantity
        unallocated_qty = impact.unallocated_quantity
        has_available_weight = (unallocated_qty > Decimal("0.0000"))
        checklist["unallocated_quantity_available"] = {
            "passed": has_available_weight,
            "total_quantity": float(impact.quantity),
            "allocated_quantity": float(impact.allocated_quantity),
            "unallocated_quantity": float(unallocated_qty),
        }
        if not has_available_weight:
            is_eligible = False
            reasons.append(
                f"No unallocated physical quantity remaining. Total: {impact.quantity} KG, "
                f"Already Allocated: {impact.allocated_quantity} KG."
            )

        # Gate 5: Independent Verification Requirement
        has_verification = True
        if version.requires_independent_verification:
            has_verification = (impact.verification_record_id is not None)
            checklist["independent_verification_present"] = {
                "passed": has_verification,
                "verification_record_id": str(impact.verification_record_id) if impact.verification_record_id else None,
            }
            if not has_verification:
                is_eligible = False
                reasons.append("Methodology mandates independent third-party verification, but no verification record is linked.")

        # Gate 6: Evidence Manifest Completeness
        manifest = impact.evidence_manifest or []
        present_types = {e.get("evidence_type", "").upper() for e in manifest}
        required_types = [t.upper() for t in version.required_evidence_types]
        missing_evidence = [t for t in required_types if t not in present_types]
        checklist["evidence_manifest_complete"] = {
            "passed": len(missing_evidence) == 0,
            "required_types": required_types,
            "present_types": list(present_types),
            "missing_types": missing_evidence,
        }
        if missing_evidence:
            # If critical evidence is missing, mark REQUIRES_REVIEW or INELIGIBLE
            requires_review = True
            reasons.append(f"Mandatory evidence types missing from manifest: {missing_evidence}")

        # Gate 7: Temporal Validity (effective date range)
        now_utc = datetime.now(timezone.utc)
        time_valid = (impact.recorded_at >= version.effective_from)
        if version.effective_to:
            time_valid = time_valid and (impact.recorded_at <= version.effective_to)
        checklist["methodology_effective_window"] = {
            "passed": time_valid,
            "impact_recorded_at": impact.recorded_at.isoformat(),
            "effective_from": version.effective_from.isoformat(),
            "effective_to": version.effective_to.isoformat() if version.effective_to else None,
        }
        if not time_valid:
            is_eligible = False
            reasons.append("Impact collection date falls outside methodology effective window.")

        # Determine Final Assessment Status
        if not is_eligible:
            final_status = AssessmentStatus.INELIGIBLE
            eligible_kg = Decimal("0.0000")
            net_credits = Decimal("0.0000")
        elif requires_review:
            final_status = AssessmentStatus.REQUIRES_REVIEW
            eligible_kg = Decimal("0.0000")
            net_credits = Decimal("0.0000")
        else:
            final_status = AssessmentStatus.ELIGIBLE
            eligible_kg = unallocated_qty

            # Calculation: NET = ELIGIBLE_KG * CONVERSION_FACTOR * (1 - (ADDITIONALITY + BASELINE + LEAKAGE))
            factor = version.credit_conversion_factor
            deduction_sum = version.additionality_discount + version.baseline_discount + version.leakage_deduction
            net_multiplier = max(Decimal("0.0000"), Decimal("1.0000") - deduction_sum)

            gross_credits = (eligible_kg * factor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            net_credits = (gross_credits * net_multiplier).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        calculation_snapshot = {
            "formula": version.calculation_formula,
            "gross_quantity_kg": float(impact.quantity),
            "unallocated_quantity_kg": float(unallocated_qty),
            "eligible_quantity_kg": float(eligible_kg),
            "conversion_factor": float(version.credit_conversion_factor),
            "additionality_discount": float(version.additionality_discount),
            "baseline_discount": float(version.baseline_discount),
            "leakage_deduction": float(version.leakage_deduction),
            "net_credit_units": float(net_credits),
            "credit_unit_name": version.credit_unit_name,
            "methodology_disclaimer": version.disclaimer,
        }

        year = now_utc.year
        asn_num = await self.assessment_repo.generate_next_assessment_number(year)

        assessment = EligibilityAssessment(
            assessment_number=asn_num,
            impact_record_id=impact.id,
            methodology_version_id=version.id,
            assessor_id=assessor.id,
            status=final_status,
            gross_quantity=impact.quantity,
            eligible_quantity=eligible_kg,
            net_credit_units=net_credits,
            validation_checklist=checklist,
            reasons=reasons,
            calculation_snapshot=calculation_snapshot,
            is_reproducible=True,
            notes=data.notes.strip() if data.notes else None,
            assessed_at=now_utc,
        )
        created = await self.assessment_repo.create(assessment)

        await self.audit_repo.record(
            action="ELIGIBILITY_ASSESSMENT_EXECUTED",
            resource=f"assessment:{created.id}",
            actor_id=assessor.id,
            actor_email=assessor.email,
            actor_role=assessor.role.value,
            metadata={
                "assessment_number": created.assessment_number,
                "status": created.status.value,
                "net_credit_units": float(created.net_credit_units),
                "reasons_count": len(reasons),
            },
        )

        logger.info(
            f"Eligibility Assessment {created.assessment_number} evaluated: {created.status.value} "
            f"({created.net_credit_units} credits) by {assessor.email}"
        )
        refreshed = await self.assessment_repo.get_by_id(created.id)
        return self._build_assessment_response(refreshed or created)

    # --------------------------------------------------------------------------
    # 2. Retrieval & Listing
    # --------------------------------------------------------------------------

    async def get_assessment_by_id(self, assessment_id: uuid.UUID, actor: User) -> EligibilityAssessmentResponse:
        """Fetch assessment by UUID with authorization checks."""
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if not assessment:
            raise NotFoundException("Eligibility assessment not found.")

        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.VERIFIER, UserRole.AUDITOR]:
            if assessment.impact_record.organization_id != actor.organization_id:
                raise ForbiddenException("Access denied: You cannot view assessments of another organization.")

        return self._build_assessment_response(assessment)

    async def list_assessments(
        self,
        actor: User,
        status: Optional[AssessmentStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[EligibilityAssessmentResponse]:
        """List assessments with filter and pagination."""
        items = await self.assessment_repo.list_assessments(status=status, skip=skip, limit=limit)
        # Apply tenant filter
        if actor.role not in [UserRole.SUPER_ADMIN, UserRole.VERIFIER, UserRole.AUDITOR]:
            items = [a for a in items if a.impact_record.organization_id == actor.organization_id]
        return [self._build_assessment_response(a) for a in items]

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _build_assessment_response(self, a: EligibilityAssessment) -> EligibilityAssessmentResponse:
        return EligibilityAssessmentResponse(
            id=a.id,
            assessment_number=a.assessment_number,
            impact_record_id=a.impact_record_id,
            impact_record_code=a.impact_record.impact_id if a.impact_record else None,
            methodology_version_id=a.methodology_version_id,
            methodology_code=a.methodology_version.methodology.code if a.methodology_version and a.methodology_version.methodology else None,
            version_tag=a.methodology_version.version_tag if a.methodology_version else None,
            assessor_id=a.assessor_id,
            assessor_name=f"{a.assessor.first_name} {a.assessor.last_name}" if a.assessor else None,
            status=a.status,
            gross_quantity=a.gross_quantity,
            eligible_quantity=a.eligible_quantity,
            net_credit_units=a.net_credit_units,
            validation_checklist=a.validation_checklist,
            reasons=a.reasons,
            calculation_snapshot=a.calculation_snapshot,
            is_reproducible=a.is_reproducible,
            notes=a.notes,
            assessed_at=a.assessed_at,
            created_at=a.created_at,
        )
