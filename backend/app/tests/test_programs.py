"""Tests for Corporate Programs and Operational Partner Management.

Validates program creation, lifecycle transitions, RBAC enforcement,
partner assignments, and tenant data isolation.
"""

from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient

from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole


@pytest.mark.asyncio
async def test_create_program_corporate_success(
    client: AsyncClient, create_user, auth_headers
):
    """Corporate brand owner creates a new plastic recovery program."""
    # 1. Setup Corporate user and organization
    corporate_user = await create_user(
        email="sustainability@danone.com", role=UserRole.CORPORATE
    )
    headers = auth_headers(corporate_user)

    # Create Corporate Organization
    org_res = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={
            "name": "Danone Global Circular",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "sustainability@danone.com",
            "country": "France",
            "city": "Paris",
        },
    )
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    # 2. Create Program
    start_date = datetime.now(timezone.utc)
    end_date = start_date + timedelta(days=180)

    payload = {
        "name": "Mediterranean Coastal Cleanup 2026",
        "description": "Post-consumer ocean-bound PET and HDPE recovery initiative.",
        "region": "MED-WEST",
        "target_kg": 50000.0,
        "allowed_material_types": [
            PlasticMaterialType.PET.value,
            PlasticMaterialType.HDPE.value,
        ],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": ProgramStatus.DRAFT.value,
    }

    res = await client.post("/api/v1/programs", headers=headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Mediterranean Coastal Cleanup 2026"
    assert data["region"] == "MED-WEST"
    assert data["target_kg"] == 50000.0
    assert data["collected_kg"] == 0.0
    assert set(data["allowed_material_types"]) == {"PET", "HDPE"}
    assert data["status"] == "DRAFT"
    assert data["organization_id"] == org_id
    assert "id" in data


@pytest.mark.asyncio
async def test_create_program_forbidden_for_non_corporate(
    client: AsyncClient, create_user, auth_headers
):
    """Collectors and unverified users cannot create programs."""
    collector = await create_user(
        email="field.collector@cleanseas.org", role=UserRole.COLLECTOR
    )
    headers = auth_headers(collector)

    payload = {
        "name": "Unauthorized Program",
        "region": "DEL",
        "target_kg": 1000.0,
        "allowed_material_types": [PlasticMaterialType.PET.value],
    }
    res = await client.post("/api/v1/programs", headers=headers, json=payload)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_update_program_lifecycle_and_targets(
    client: AsyncClient, create_user, auth_headers
):
    """Corporate owner can update program metadata and transition status."""
    corporate_user = await create_user(
        email="lead@unilever.com", role=UserRole.CORPORATE
    )
    headers = auth_headers(corporate_user)

    # Create Org
    org_res = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={
            "name": "Unilever Sustainable Packaging",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "packaging@unilever.com",
        },
    )
    assert org_res.status_code == 201

    # Create Program
    res = await client.post(
        "/api/v1/programs",
        headers=headers,
        json={
            "name": "Ganges Basin Initiative",
            "region": "DEL",
            "target_kg": 10000.0,
            "allowed_material_types": [PlasticMaterialType.PP.value],
            "status": ProgramStatus.DRAFT.value,
        },
    )
    assert res.status_code == 201
    program_id = res.json()["id"]

    # Update Program (transition to ACTIVE and update target)
    update_res = await client.patch(
        f"/api/v1/programs/{program_id}",
        headers=headers,
        json={
            "target_kg": 25000.0,
            "status": ProgramStatus.ACTIVE.value,
            "allowed_material_types": [
                PlasticMaterialType.PP.value,
                PlasticMaterialType.PET.value,
            ],
        },
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["target_kg"] == 25000.0
    assert updated_data["status"] == "ACTIVE"
    assert set(updated_data["allowed_material_types"]) == {"PP", "PET"}


@pytest.mark.asyncio
async def test_unauthorized_program_update_denied(
    client: AsyncClient, create_user, auth_headers
):
    """A corporate owner from Org B cannot modify Org A's program."""
    corp_a = await create_user(email="corp.a@brand-a.com", role=UserRole.CORPORATE)
    headers_a = auth_headers(corp_a)
    await client.post(
        "/api/v1/organizations",
        headers=headers_a,
        json={
            "name": "Brand A Corp",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "admin@brand-a.com",
        },
    )
    res_a = await client.post(
        "/api/v1/programs",
        headers=headers_a,
        json={
            "name": "Brand A Program",
            "region": "MUM",
            "target_kg": 5000.0,
            "allowed_material_types": [PlasticMaterialType.PET.value],
        },
    )
    prog_id = res_a.json()["id"]

    # Corp B tries to tamper
    corp_b = await create_user(email="corp.b@brand-b.com", role=UserRole.CORPORATE)
    headers_b = auth_headers(corp_b)
    await client.post(
        "/api/v1/organizations",
        headers=headers_b,
        json={
            "name": "Brand B Corp",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "admin@brand-b.com",
        },
    )

    tamper_res = await client.patch(
        f"/api/v1/programs/{prog_id}",
        headers=headers_b,
        json={"name": "Hacked Program"},
    )
    assert tamper_res.status_code == 403


@pytest.mark.asyncio
async def test_assign_and_remove_program_partner(
    client: AsyncClient, create_user, auth_headers
):
    """Assign operational collector partner to program and list partners."""
    # 1. Corporate creator
    corp = await create_user(email="programs@nestle.com", role=UserRole.CORPORATE)
    corp_headers = auth_headers(corp)
    await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Nestle Circular",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "programs@nestle.com",
        },
    )

    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Southeast Asia Recovery 2026",
            "region": "SEA",
            "target_kg": 150000.0,
            "allowed_material_types": [
                PlasticMaterialType.PET.value,
                PlasticMaterialType.HDPE.value,
            ],
            "status": ProgramStatus.ACTIVE.value,
        },
    )
    program_id = prog_res.json()["id"]

    # 2. Collector Org
    collector = await create_user(
        email="admin@oceanrecovery.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(collector)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Ocean Recovery Alliance",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "admin@oceanrecovery.org",
        },
    )
    collector_org_id = col_org_res.json()["id"]

    # 3. Assign Collector Partner
    assign_res = await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={
            "organization_id": collector_org_id,
            "assigned_role": "COLLECTOR",
            "region_scope": "SEA",
            "notes": "Primary coastal collection partner",
        },
    )
    assert assign_res.status_code == 201
    assign_data = assign_res.json()
    assert assign_data["organization_id"] == collector_org_id
    assert assign_data["assigned_role"] == "COLLECTOR"

    # 4. Duplicate assignment fails with 409
    dup_res = await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={
            "organization_id": collector_org_id,
            "assigned_role": "COLLECTOR",
        },
    )
    assert dup_res.status_code == 409

    # 5. List Partners
    list_partners_res = await client.get(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
    )
    assert list_partners_res.status_code == 200
    partners = list_partners_res.json()
    assert len(partners) == 1
    assert partners[0]["organization_name"] == "Ocean Recovery Alliance"

    # 6. Remove Partner
    del_res = await client.delete(
        f"/api/v1/programs/{program_id}/partners/{collector_org_id}",
        headers=corp_headers,
    )
    assert del_res.status_code == 200

    # 7. Verify empty list
    list_after = await client.get(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
    )
    assert list_after.status_code == 200
    assert len(list_after.json()) == 0
