"""PLASTIFY SENTINEL Risk and Anomaly Detection Endpoints.

Provides APIs to inspect automated risk findings and trigger on-demand anomaly detection runs.
"""

import logging
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    SentinelServiceDep,
    require_roles,
)
from app.models.user import UserRole
from app.schemas.sentinel import SentinelResultResponse, SentinelRunRequest

logger = logging.getLogger("plastify.api.sentinel")

router = APIRouter(prefix="/sentinel", tags=["sentinel"])


@router.get(
    "/{recovery_id}",
    response_model=SentinelResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Sentinel risk findings and score for a recovery event",
    description=(
        "Retrieves the automated risk score, categorical risk tier (LOW, MEDIUM, HIGH, CRITICAL), "
        "synthesized executive summary, and granular detector anomaly findings."
    ),
)
async def get_sentinel_risk_report(
    recovery_id: uuid.UUID,
    sentinel_service: SentinelServiceDep,
    current_user: CurrentUserDep,
) -> SentinelResultResponse:
    """Retrieve existing or compute real-time Sentinel risk assessment."""
    return await sentinel_service.get_sentinel_result(
        recovery_id=recovery_id, requester=current_user
    )


@router.post(
    "/{recovery_id}/run",
    response_model=SentinelResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute Sentinel risk evaluation on a recovery event",
    description=(
        "Executes all pluggable detectors (weight, GPS, chronology, duplicate evidence, "
        "delivery reconciliation, and behavioral signatures). Supports synchronous or async Celery execution."
    ),
)
async def run_sentinel_evaluation(
    recovery_id: uuid.UUID,
    payload: Optional[SentinelRunRequest] = None,
    sentinel_service: SentinelServiceDep = None,
    current_user: CurrentUserDep = None,
    _=Depends(
        require_roles(
            UserRole.VERIFIER,
            UserRole.AUDITOR,
            UserRole.CORPORATE,
            UserRole.SUPER_ADMIN,
        )
    ),
) -> SentinelResultResponse:
    """Trigger on-demand or queued asynchronous Sentinel risk evaluation."""
    async_mode = payload.async_run if payload else False
    options = payload.detector_options if payload else None

    return await sentinel_service.run_analysis(
        recovery_id=recovery_id,
        requester=current_user,
        async_run=async_mode,
        detector_options=options,
    )
