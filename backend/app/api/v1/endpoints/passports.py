"""PLASTIFY Digital Product Passport (DPP) & Material Passport API Endpoints.

Provides public, QR-ready verifiable circular provenance:
    Product -> Upcycling Batch -> Material Batch -> Recovery Event(s)
With strict physical segregation of mass accounting metrics.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import PassportServiceDep, RecyclingServiceDep
from app.schemas.circular import (
    MaterialPassportResponse,
    ProductPassportProvenanceResponse,
)

router = APIRouter(prefix="/passports", tags=["Digital Product Passports"])


@router.get(
    "/product/{passport_id}",
    response_model=ProductPassportProvenanceResponse,
    summary="Resolve Digital Product Passport",
    description=(
        "Public QR-ready endpoint providing unalterable provenance and mass balance accounting "
        "tracing a circular product back through upcycling, recycling, and origin recovery events."
    ),
)
async def get_product_passport(
    passport_id: str,
    passport_service: PassportServiceDep,
) -> ProductPassportProvenanceResponse:
    """Public Digital Product Passport resolution."""
    return await passport_service.get_product_passport_provenance(passport_id)


@router.get(
    "/material/{passport_code}",
    response_model=MaterialPassportResponse,
    summary="Resolve Material Passport",
    description="Retrieve Digital Material Passport credentials for an industrial recycling batch.",
)
async def get_material_passport(
    passport_code: str,
    recycling_service: RecyclingServiceDep,
) -> MaterialPassportResponse:
    """Public Material Passport resolution."""
    return await recycling_service.get_material_passport(passport_code)
