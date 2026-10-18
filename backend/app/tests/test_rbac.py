"""Tests for Central Role-Based Access Control (RBAC) System."""

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from app.core.dependencies import require_roles
from app.models.user import UserRole


@pytest.mark.asyncio
async def test_super_admin_bypasses_role_restrictions(client: AsyncClient, create_user, auth_headers):
    """SUPER_ADMIN can access endpoints restricted to specific sub-roles."""
    admin = await create_user(
        email="superadmin.rbac@plastify.io", role=UserRole.SUPER_ADMIN
    )
    headers = auth_headers(admin)

    # Super Admin can update another user's status
    other_user = await create_user(email="other.user@plastify.io")
    res = await client.patch(
        f"/api/v1/auth/users/{other_user.id}/status",
        headers=headers,
        json={"is_active": True},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_non_admin_denied_access_to_admin_endpoints(
    client: AsyncClient, create_user, auth_headers
):
    """Non-admin user (e.g. COLLECTOR) is denied access (403 Forbidden) to admin endpoints."""
    collector = await create_user(
        email="collector.rbac@plastify.io", role=UserRole.COLLECTOR
    )
    headers = auth_headers(collector)

    target_user = await create_user(email="target.rbac@plastify.io")
    res = await client.patch(
        f"/api/v1/auth/users/{target_user.id}/status",
        headers=headers,
        json={"is_active": False},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_endpoint_level_rbac_dependency(client: AsyncClient, create_user, auth_headers):
    """Test require_roles dependency enforcement at endpoint level."""
    test_router = APIRouter(prefix="/api/v1/test-rbac", tags=["Test RBAC"])

    @test_router.get(
        "/verifier-only",
        dependencies=[Depends(require_roles(UserRole.VERIFIER, UserRole.AUDITOR))],
    )
    async def verifier_only_route():
        return {"status": "authorized"}

    app_instance = client._transport.app
    app_instance.include_router(test_router)

    verifier = await create_user(email="verifier.rbac@plastify.io", role=UserRole.VERIFIER)
    auditor = await create_user(email="auditor.rbac@plastify.io", role=UserRole.AUDITOR)
    recycler = await create_user(email="recycler.rbac@plastify.io", role=UserRole.RECYCLER)
    corporate = await create_user(email="corporate.rbac@plastify.io", role=UserRole.CORPORATE)

    # 1. VERIFIER: allowed
    res_verifier = await client.get(
        "/api/v1/test-rbac/verifier-only", headers=auth_headers(verifier)
    )
    assert res_verifier.status_code == 200

    # 2. AUDITOR: allowed
    res_auditor = await client.get(
        "/api/v1/test-rbac/verifier-only", headers=auth_headers(auditor)
    )
    assert res_auditor.status_code == 200

    # 3. RECYCLER: forbidden
    res_recycler = await client.get(
        "/api/v1/test-rbac/verifier-only", headers=auth_headers(recycler)
    )
    assert res_recycler.status_code == 403

    # 4. CORPORATE: forbidden
    res_corporate = await client.get(
        "/api/v1/test-rbac/verifier-only", headers=auth_headers(corporate)
    )
    assert res_corporate.status_code == 403
