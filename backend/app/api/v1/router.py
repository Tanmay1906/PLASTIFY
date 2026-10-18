"""PLASTIFY API v1 Router Aggregator.

Combines all v1 domain routers under the versioned route prefix.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.custody import router as custody_router
from app.api.v1.endpoints.evidence import router as evidence_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.logistics import router as logistics_router
from app.api.v1.endpoints.organizations import router as organizations_router
from app.api.v1.endpoints.programs import router as programs_router
from app.api.v1.endpoints.recoveries import router as recoveries_router
from app.api.v1.endpoints.system import router as system_router
from app.api.v1.endpoints.verification import router as verification_router
from app.api.v1.endpoints.sentinel import router as sentinel_router
from app.api.v1.endpoints.recycling import router as recycling_router
from app.api.v1.endpoints.upcycling import router as upcycling_router
from app.api.v1.endpoints.passports import router as passports_router
from app.api.v1.endpoints.impact import router as impact_router
from app.api.v1.endpoints.credit import router as credit_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router)
api_v1_router.include_router(system_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(programs_router)
api_v1_router.include_router(recoveries_router)
api_v1_router.include_router(evidence_router)
api_v1_router.include_router(custody_router)
api_v1_router.include_router(logistics_router)
api_v1_router.include_router(verification_router)
api_v1_router.include_router(sentinel_router)
api_v1_router.include_router(recycling_router)
api_v1_router.include_router(upcycling_router)
api_v1_router.include_router(passports_router)
api_v1_router.include_router(impact_router)
api_v1_router.include_router(credit_router)
