"""Tests for Organizations, Members, Partnerships, and Tenant Isolation."""

import pytest
from httpx import AsyncClient

from app.models.organization import OrganizationType, OrgMemberRole, PartnerStatus
from app.models.user import UserRole


@pytest.mark.asyncio
async def test_create_organization(client: AsyncClient, create_user, auth_headers):
    """Test creating an organization assigns the creator as Admin."""
    user = await create_user(email="founder@circular.io", role=UserRole.CORPORATE)
    headers = auth_headers(user)

    payload = {
        "name": "Circular Packaging Corp",
        "org_type": OrganizationType.CORPORATE.value,
        "contact_email": "contact@circular.io",
        "country": "Germany",
        "city": "Berlin",
        "description": "Leading sustainable circular polymers.",
    }
    response = await client.post("/api/v1/organizations", headers=headers, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Circular Packaging Corp"
    assert data["slug"] == "circular-packaging-corp"
    assert data["org_type"] == "CORPORATE"
    assert data["country"] == "Germany"
    assert "id" in data


@pytest.mark.asyncio
async def test_duplicate_organization_name(client: AsyncClient, create_user, auth_headers):
    """Test creating an organization with an existing name returns 409 Conflict."""
    user = await create_user(email="founder2@circular.io")
    headers = auth_headers(user)

    payload = {
        "name": "Unique Plastics",
        "org_type": OrganizationType.RECYCLER.value,
        "contact_email": "info@unique.io",
    }
    res1 = await client.post("/api/v1/organizations", headers=headers, json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/organizations", headers=headers, json=payload)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "RESOURCE_CONFLICT"


@pytest.mark.asyncio
async def test_cross_organization_access_denial_idor(
    client: AsyncClient, create_user, auth_headers
):
    """Test that users from Org A cannot access or modify private data of Org B (IDOR prevention)."""
    user_a = await create_user(email="user.a@orga.com")
    user_b = await create_user(email="user.b@orgb.com")

    # 1. Create Org A
    res_a = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(user_a),
        json={
            "name": "Organization Alpha",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "alpha@plastify.io",
        },
    )
    org_a_id = res_a.json()["id"]

    # 2. Create Org B
    res_b = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(user_b),
        json={
            "name": "Organization Beta",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "beta@plastify.io",
        },
    )
    org_b_id = res_b.json()["id"]

    # 3. User A attempts to view Org B profile: 403 Forbidden!
    blocked_get = await client.get(
        f"/api/v1/organizations/{org_b_id}", headers=auth_headers(user_a)
    )
    assert blocked_get.status_code == 403
    assert blocked_get.json()["error"]["code"] == "FORBIDDEN"

    # 4. User A attempts to update Org B profile: 403 Forbidden!
    blocked_patch = await client.patch(
        f"/api/v1/organizations/{org_b_id}",
        headers=auth_headers(user_a),
        json={"name": "Hacked Name"},
    )
    assert blocked_patch.status_code == 403

    # 5. User A attempts to view Org B members: 403 Forbidden!
    blocked_members = await client.get(
        f"/api/v1/organizations/{org_b_id}/members", headers=auth_headers(user_a)
    )
    assert blocked_members.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_access_any_organization(
    client: AsyncClient, create_user, auth_headers
):
    """SUPER_ADMIN can access any organization regardless of tenant boundary."""
    admin = await create_user(email="super.audit@plastify.io", role=UserRole.SUPER_ADMIN)
    founder = await create_user(email="founder.audit@plastify.io")

    res = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(founder),
        json={
            "name": "Tenant Gamma",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "gamma@plastify.io",
        },
    )
    org_id = res.json()["id"]

    # Super Admin accesses Tenant Gamma
    admin_get = await client.get(
        f"/api/v1/organizations/{org_id}", headers=auth_headers(admin)
    )
    assert admin_get.status_code == 200
    assert admin_get.json()["name"] == "Tenant Gamma"


@pytest.mark.asyncio
async def test_organization_member_management(
    client: AsyncClient, create_user, auth_headers
):
    """Test inviting, updating, and removing organization members."""
    admin_user = await create_user(email="admin.org@test.io")
    member_user = await create_user(email="member.candidate@test.io")

    # Create Org
    res_org = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(admin_user),
        json={
            "name": "Recycling Alliance",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "alliance@plastify.io",
        },
    )
    org_id = res_org.json()["id"]
    admin_headers = auth_headers(admin_user)

    # 1. Add member
    add_res = await client.post(
        f"/api/v1/organizations/{org_id}/members",
        headers=admin_headers,
        json={
            "user_id": str(member_user.id),
            "role": OrgMemberRole.MEMBER.value,
        },
    )
    assert add_res.status_code == 201
    assert add_res.json()["user_id"] == str(member_user.id)
    assert add_res.json()["role"] == "MEMBER"

    # 2. List members
    list_res = await client.get(
        f"/api/v1/organizations/{org_id}/members", headers=admin_headers
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 2  # Admin + Member

    # 3. Update member role
    update_res = await client.patch(
        f"/api/v1/organizations/{org_id}/members/{member_user.id}",
        headers=admin_headers,
        json={"role": OrgMemberRole.VIEWER.value},
    )
    assert update_res.status_code == 200
    assert update_res.json()["role"] == "VIEWER"

    # 4. Remove member
    del_res = await client.delete(
        f"/api/v1/organizations/{org_id}/members/{member_user.id}",
        headers=admin_headers,
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 5. Verify member is removed
    after_list = await client.get(
        f"/api/v1/organizations/{org_id}/members", headers=admin_headers
    )
    assert len(after_list.json()) == 1


@pytest.mark.asyncio
async def test_partner_relationship_lifecycle(
    client: AsyncClient, create_user, auth_headers
):
    """Test proposing and accepting partner agreements between organizations."""
    user1 = await create_user(email="partner1@plastify.io")
    user2 = await create_user(email="partner2@plastify.io")

    # Create Org 1
    org1_res = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(user1),
        json={
            "name": "Collector Network 1",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "net1@plastify.io",
        },
    )
    org1_id = org1_res.json()["id"]

    # Create Org 2
    org2_res = await client.post(
        "/api/v1/organizations",
        headers=auth_headers(user2),
        json={
            "name": "Recycling Plant 2",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "plant2@plastify.io",
        },
    )
    org2_id = org2_res.json()["id"]

    # 1. Org 1 requests partnership with Org 2
    req_res = await client.post(
        f"/api/v1/organizations/{org1_id}/partners",
        headers=auth_headers(user1),
        json={
            "partner_org_id": org2_id,
            "relationship_type": "COLLECTION_SUPPLY",
            "notes": "Supply sorted PET to recycling facility",
        },
    )
    assert req_res.status_code == 201
    partnership = req_res.json()
    assert partnership["status"] == "PENDING"
    partnership_id = partnership["id"]

    # 2. Org 2 lists partnerships and sees the pending request
    list_p = await client.get(
        f"/api/v1/organizations/{org2_id}/partners", headers=auth_headers(user2)
    )
    assert list_p.status_code == 200
    assert len(list_p.json()) == 1

    # 3. Org 2 accepts the partnership
    accept_res = await client.patch(
        f"/api/v1/organizations/{org2_id}/partners/{partnership_id}",
        headers=auth_headers(user2),
        json={"status": PartnerStatus.ACTIVE.value},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "ACTIVE"
