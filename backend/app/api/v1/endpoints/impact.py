"""PLASTIFY Impact Ledger and Methodology API Endpoints.

Handles:
- Verified physical impact record registration from collections and recycling batches
- Impact record retrieval and tenant-scoped listing
- Traceable superseding / audit corrections
- Methodology standards and immutable version registration
- Deterministic, reproducible credit eligibility assessments
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    EligibilityServiceDep,
    ImpactServiceDep,
    MethodologyServiceDep,
    require_roles,
)
from app.models.impact import AssessmentStatus, ImpactOutcomeType, ImpactStatus
from app.models.user import UserRole
from app.schemas.impact import (
    EligibilityAssessmentCreateRequest,
    EligibilityAssessmentResponse,
    ImpactRecordCreateRequest,
    ImpactRecordResponse,
    ImpactRecordSupersedeRequest,
    MethodologyCreateRequest,
    MethodologyResponse,
    MethodologyVersionCreateRequest,
    MethodologyVersionResponse,
)

router = APIRouter(prefix="/impact", tags=["Impact Ledger & Methodology Engine"])


# ------------------------------------------------------------------------------
# 1. Impact Records
# ------------------------------------------------------------------------------

@router.post(
    "/records",
    response_model=ImpactRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Verified Physical Impact",
    description="Admit an officially verified recovery event or completed recycling batch into the authoritative Impact Ledger.",
)
async def register_impact_record(
    payload: ImpactRecordCreateRequest,
    impact_service: ImpactServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(
        UserRole.CORPORATE,
        UserRole.COLLECTOR,
        UserRole.RECYCLER,
        UserRole.UPCYCLER,
        UserRole.VERIFIER,
        UserRole.SUPER_ADMIN,
    )),
) -> ImpactRecordResponse:
    """Register verified impact record anchored to source provenance."""
    return await impact_service.register_impact_from_source(payload, current_user)


@router.get(
    "/records",
    response_model=List[ImpactRecordResponse],
    summary="List Impact Records",
    description="Retrieve impact records with tenant isolation and optional outcome_type and status filters.",
)
async def list_impact_records(
    impact_service: ImpactServiceDep,
    current_user: CurrentUserDep,
    outcome_type: Optional[ImpactOutcomeType] = Query(None, description="Filter by physical outcome"),
    status: Optional[ImpactStatus] = Query(None, description="Filter by impact status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[ImpactRecordResponse]:
    """List impact records accessible to current user."""
    return await impact_service.list_impact_records(
        actor=current_user,
        outcome_type=outcome_type,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/records/{impact_id}",
    response_model=ImpactRecordResponse,
    summary="Get Impact Record Details",
    description="Fetch a specific impact record by UUID including source anchors, evidence manifest, and allocations.",
)
async def get_impact_record(
    impact_id: uuid.UUID,
    impact_service: ImpactServiceDep,
    current_user: CurrentUserDep,
) -> ImpactRecordResponse:
    """Fetch impact record by ID."""
    return await impact_service.get_impact_by_id(impact_id, current_user)


@router.post(
    "/records/{impact_id}/supersede",
    response_model=ImpactRecordResponse,
    summary="Supersede Impact Record with Audit Correction",
    description="Traceably supersede an existing impact record with an audit correction. Preserves historical linkage.",
)
async def supersede_impact_record(
    impact_id: uuid.UUID,
    payload: ImpactRecordSupersedeRequest,
    impact_service: ImpactServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.AUDITOR)),
) -> ImpactRecordResponse:
    """Supersede impact record with documented justification."""
    return await impact_service.supersede_impact_record(impact_id, payload, current_user)


# ------------------------------------------------------------------------------
# 2. Methodologies & Versions
# ------------------------------------------------------------------------------

@router.post(
    "/methodologies",
    response_model=MethodologyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Accounting Methodology",
    description="Register a new crediting protocol definition (e.g. PLASTIFY-COL-v1, PWRS-ALIGN).",
)
async def create_methodology(
    payload: MethodologyCreateRequest,
    methodology_service: MethodologyServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.AUDITOR)),
) -> MethodologyResponse:
    """Register methodology."""
    return await methodology_service.create_methodology(payload, current_user)


@router.get(
    "/methodologies",
    response_model=List[MethodologyResponse],
    summary="List Active Methodologies",
    description="Retrieve all active accounting standards and their registered version tags.",
)
async def list_methodologies(
    methodology_service: MethodologyServiceDep,
    current_user: CurrentUserDep,
) -> List[MethodologyResponse]:
    """List methodologies."""
    return await methodology_service.list_methodologies()


@router.get(
    "/methodologies/{methodology_id}",
    response_model=MethodologyResponse,
    summary="Get Methodology Details",
    description="Fetch a specific methodology including all version definitions.",
)
async def get_methodology(
    methodology_id: uuid.UUID,
    methodology_service: MethodologyServiceDep,
    current_user: CurrentUserDep,
) -> MethodologyResponse:
    """Fetch methodology by UUID."""
    return await methodology_service.get_methodology_by_id(methodology_id)


@router.post(
    "/methodologies/{methodology_id}/versions",
    response_model=MethodologyVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Immutable Methodology Version",
    description="Publish an immutable version tag with activity conversion factors, baseline discounts, and evidence gates.",
)
async def create_methodology_version(
    methodology_id: uuid.UUID,
    payload: MethodologyVersionCreateRequest,
    methodology_service: MethodologyServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.AUDITOR)),
) -> MethodologyVersionResponse:
    """Create immutable methodology version."""
    return await methodology_service.create_version(methodology_id, payload, current_user)


@router.get(
    "/methodologies/versions/{version_id}",
    response_model=MethodologyVersionResponse,
    summary="Get Methodology Version Details",
    description="Fetch exact factors, evidence requirements, and calculation formula for a version.",
)
async def get_methodology_version(
    version_id: uuid.UUID,
    methodology_service: MethodologyServiceDep,
    current_user: CurrentUserDep,
) -> MethodologyVersionResponse:
    """Fetch methodology version by UUID."""
    return await methodology_service.get_version_by_id(version_id)


# ------------------------------------------------------------------------------
# 3. Eligibility Assessments
# ------------------------------------------------------------------------------

@router.post(
    "/assessments",
    response_model=EligibilityAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run Credit Eligibility Assessment",
    description="Execute reproducible evaluation of an Impact Record against a Methodology Version. Generates calculation snapshot.",
)
async def assess_eligibility(
    payload: EligibilityAssessmentCreateRequest,
    eligibility_service: EligibilityServiceDep,
    current_user: CurrentUserDep,
    _=Depends(require_roles(
        UserRole.CORPORATE,
        UserRole.COLLECTOR,
        UserRole.RECYCLER,
        UserRole.VERIFIER,
        UserRole.AUDITOR,
        UserRole.SUPER_ADMIN,
    )),
) -> EligibilityAssessmentResponse:
    """Assess impact record eligibility."""
    return await eligibility_service.assess_impact_eligibility(payload, current_user)


@router.get(
    "/assessments",
    response_model=List[EligibilityAssessmentResponse],
    summary="List Eligibility Assessments",
    description="Retrieve eligibility assessments with status filter and tenant isolation.",
)
async def list_assessments(
    eligibility_service: EligibilityServiceDep,
    current_user: CurrentUserDep,
    status: Optional[AssessmentStatus] = Query(None, description="Filter by assessment determination"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> List[EligibilityAssessmentResponse]:
    """List assessments."""
    return await eligibility_service.list_assessments(
        actor=current_user,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/assessments/{assessment_id}",
    response_model=EligibilityAssessmentResponse,
    summary="Get Eligibility Assessment Details",
    description="Fetch a specific assessment snapshot by UUID.",
)
async def get_assessment(
    assessment_id: uuid.UUID,
    eligibility_service: EligibilityServiceDep,
    current_user: CurrentUserDep,
) -> EligibilityAssessmentResponse:
    """Fetch assessment by ID."""
    return await eligibility_service.get_assessment_by_id(assessment_id, current_user)
