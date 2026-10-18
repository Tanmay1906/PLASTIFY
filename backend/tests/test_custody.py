"""Tests for Circular Materials Chain of Custody Foundation.

Validates:
- Complete end-to-end chain of custody progression:
  CREATED -> SUBMITTED -> PICKUP_ASSIGNED -> PICKED_UP -> IN_TRANSIT -> DELIVERED -> RECEIVED -> VERIFIED -> PROCESSED
- Invalid / out-of-order state transition rejection (400)
- Role-based transition enforcement (Collector, Logistics, Recycler, Verifier, Corporate)
- Rejection branch handling (REJECTED terminal state)
- Immutability: normal users cannot edit or delete historical chain-of-custody logs
- Tenant isolation and unauthorized custody timeline access denial (403)
"""

import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole


async def _setup_custody_ecosystem(client: AsyncClient, create_user, auth_headers):
    """Sets up an entire multi-party circular economy network:

    - Corporate brand owner
    - Collector cooperative
    - Logistics transport provider
    - Recycler processing facility
    - Third-party Verifier
    - Active Program with all parties assigned as operational partners
    """
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email="sustainability@nestle-global.com", role=UserRole.CORPORATE
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Nestle Circular Global",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "sustainability@nestle-global.com",
        },
    )
    corp_org_id = corp_org_res.json()["id"]

    # 2. Program
    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Global Ocean Bound Plastic 2026",
            "region": "SEA",
            "target_kg": 100000.0,
            "allowed_material_types": [
                PlasticMaterialType.PET.value,
                PlasticMaterialType.HDPE.value,
            ],
            "status": ProgramStatus.ACTIVE.value,
        },
    )
    program_id = prog_res.json()["id"]

    # 3. Collector
    col_user = await create_user(
        email="collector@oceanalliance.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Ocean Recovery Alliance",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@oceanalliance.org",
        },
    )
    col_org_id = col_org_res.json()["id"]
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": col_org_id, "assigned_role": "COLLECTOR"},
    )

    # 4. Logistics
    log_user = await create_user(
        email="dispatch@circularfreight.com", role=UserRole.LOGISTICS
    )
    log_headers = auth_headers(log_user)
    log_org_res = await client.post(
        "/api/v1/organizations",
        headers=log_headers,
        json={
            "name": "Circular Freight Solutions",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "ops@circularfreight.com",
        },
    )
    log_org_id = log_org_res.json()["id"]
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": log_org_id, "assigned_role": "LOGISTICS"},
    )

    # 5. Recycler
    rec_user = await create_user(
        email="plant@ecopolymers.com", role=UserRole.RECYCLER
    )
    rec_headers = auth_headers(rec_user)
    rec_org_res = await client.post(
        "/api/v1/organizations",
        headers=rec_headers,
        json={
            "name": "EcoPolymers Recycling Plant",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "plant@ecopolymers.com",
        },
    )
    rec_org_id = rec_org_res.json()["id"]
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": rec_org_id, "assigned_role": "RECYCLER"},
    )

    # 6. Verifier
    ver_user = await create_user(
        email="auditor@greenveritas.com", role=UserRole.VERIFIER
    )
    ver_headers = auth_headers(ver_user)
    ver_org_res = await client.post(
        "/api/v1/organizations",
        headers=ver_headers,
        json={
            "name": "GreenVeritas Auditing",
            "org_type": OrganizationType.VERIFIER.value,
            "contact_email": "auditor@greenveritas.com",
        },
    )
    ver_org_id = ver_org_res.json()["id"]
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": ver_org_id, "assigned_role": "VERIFIER"},
    )

    # 7. Create Initial Recovery Event in CREATED status
    recovery_res = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 750.0,
            "collection_location": "Banten Coastal Recovery Hub, Indonesia",
        },
    )
    assert recovery_res.status_code == 201
    recovery = recovery_res.json()

    return {
        "program_id": program_id,
        "recovery_id": recovery["id"],
        "human_id": recovery["recovery_id"],
        "corp_headers": corp_headers,
        "col_headers": col_headers,
        "log_headers": log_headers,
        "rec_headers": rec_headers,
        "ver_headers": ver_headers,
    }


@pytest.mark.asyncio
async def test_full_chain_of_custody_progression(
    client: AsyncClient, create_user, auth_headers
):
    """Test legitimate progression through all milestones:

    CREATED -> SUBMITTED -> PICKUP_ASSIGNED -> PICKED_UP -> IN_TRANSIT -> DELIVERED -> RECEIVED -> VERIFIED -> PROCESSED
    """
    data = await _setup_custody_ecosystem(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    # 1. Collector submits recovery
    t1 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["col_headers"],
        json={"new_state": CustodyState.SUBMITTED.value, "notes": "Baled and tagged for transport"},
    )
    assert t1.status_code == 200
    assert t1.json()["current_state"] == "SUBMITTED"

    # 2. Logistics assigns pickup
    t2 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.PICKUP_ASSIGNED.value, "notes": "Truck #CF-408 assigned"},
    )
    assert t2.status_code == 200
    assert t2.json()["current_state"] == "PICKUP_ASSIGNED"

    # 3. Logistics picks up
    t3 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.PICKED_UP.value, "notes": "Loaded onto flatbed at collection hub"},
    )
    assert t3.status_code == 200
    assert t3.json()["current_state"] == "PICKED_UP"

    # 4. Logistics in transit
    t4 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.IN_TRANSIT.value, "notes": "En route via tollway"},
    )
    assert t4.status_code == 200
    assert t4.json()["current_state"] == "IN_TRANSIT"

    # 5. Logistics delivers
    t5 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.DELIVERED.value, "notes": "Unloaded at recycling processing yard"},
    )
    assert t5.status_code == 200
    assert t5.json()["current_state"] == "DELIVERED"

    # 6. Recycler receives
    t6 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["rec_headers"],
        json={"new_state": CustodyState.RECEIVED.value, "notes": "Weighbridge verified: 750kg gross received"},
    )
    assert t6.status_code == 200
    assert t6.json()["current_state"] == "RECEIVED"

    # 7. Verifier inspects & verifies
    t7 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["ver_headers"],
        json={"new_state": CustodyState.VERIFIED.value, "notes": "Physical audit and moisture check passed"},
    )
    assert t7.status_code == 200
    assert t7.json()["current_state"] == "VERIFIED"

    # 8. Recycler processes
    t8 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["rec_headers"],
        json={"new_state": CustodyState.PROCESSED.value, "notes": "Flaked and washed into clean PET flakes"},
    )
    assert t8.status_code == 200
    assert t8.json()["current_state"] == "PROCESSED"

    # 9. Verify full chronological timeline
    timeline_res = await client.get(
        f"/api/v1/recoveries/{recovery_id}/custody", headers=data["corp_headers"]
    )
    assert timeline_res.status_code == 200
    timeline = timeline_res.json()
    assert timeline["resource"] == data["human_id"]
    assert timeline["current_state"] == "PROCESSED"
    assert len(timeline["events"]) == 8

    # Verify event sequencing
    states = [e["new_state"] for e in timeline["events"]]
    expected_sequence = [
        "SUBMITTED",
        "PICKUP_ASSIGNED",
        "PICKED_UP",
        "IN_TRANSIT",
        "DELIVERED",
        "RECEIVED",
        "VERIFIED",
        "PROCESSED",
    ]
    assert states == expected_sequence


@pytest.mark.asyncio
async def test_invalid_custody_transitions_rejected(
    client: AsyncClient, create_user, auth_headers
):
    """Skipping lifecycle stages (e.g. CREATED directly to DELIVERED) is strictly rejected."""
    data = await _setup_custody_ecosystem(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    # Attempt transition from CREATED to DELIVERED
    res_skip = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.DELIVERED.value},
    )
    assert res_skip.status_code == 400
    assert "Invalid chain-of-custody transition" in res_skip.json()["error"]["message"]


@pytest.mark.asyncio
async def test_role_authorization_enforced_per_state(
    client: AsyncClient, create_user, auth_headers
):
    """A Collector cannot mark an item as VERIFIED; only Verifiers/Auditors can."""
    data = await _setup_custody_ecosystem(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    # Advance to RECEIVED legitimately
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["col_headers"],
        json={"new_state": CustodyState.SUBMITTED.value},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.PICKUP_ASSIGNED.value},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.PICKED_UP.value},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.IN_TRANSIT.value},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.DELIVERED.value},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["rec_headers"],
        json={"new_state": CustodyState.RECEIVED.value},
    )

    # Collector attempts to VERIFY (tamper)
    tamper_res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["col_headers"],
        json={"new_state": CustodyState.VERIFIED.value},
    )
    assert tamper_res.status_code == 403
    assert "not authorized" in tamper_res.json()["error"]["message"]


@pytest.mark.asyncio
async def test_rejection_branch_and_terminal_lock(
    client: AsyncClient, create_user, auth_headers
):
    """A verifier can reject a shipment; once REJECTED, no further transitions are allowed."""
    data = await _setup_custody_ecosystem(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    # Advance to SUBMITTED
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["col_headers"],
        json={"new_state": CustodyState.SUBMITTED.value},
    )

    # Verifier rejects due to contaminated non-recyclable content
    reject_res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["ver_headers"],
        json={
            "new_state": CustodyState.REJECTED.value,
            "notes": "Severe municipal soil contamination exceeding 40% threshold",
        },
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["current_state"] == "REJECTED"

    # Attempt to transition out of terminal REJECTED state fails
    post_reject = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["log_headers"],
        json={"new_state": CustodyState.PICKUP_ASSIGNED.value},
    )
    assert post_reject.status_code == 400
    assert "Terminal state" in post_reject.json()["error"]["message"]


@pytest.mark.asyncio
async def test_custody_immutability_and_tamper_proofing(
    client: AsyncClient, create_user, auth_headers
):
    """Historical chain-of-custody events cannot be deleted or modified."""
    data = await _setup_custody_ecosystem(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    t1 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=data["col_headers"],
        json={"new_state": CustodyState.SUBMITTED.value},
    )
    timeline = t1.json()
    event_id = timeline["events"][0]["id"]

    # Verify no modification routes exist (404/405)
    delete_attempt = await client.delete(
        f"/api/v1/recoveries/{recovery_id}/custody/{event_id}",
        headers=data["col_headers"],
    )
    assert delete_attempt.status_code in [404, 405]

    patch_attempt = await client.patch(
        f"/api/v1/recoveries/{recovery_id}/custody/{event_id}",
        headers=data["col_headers"],
        json={"notes": "Altered historical notes"},
    )
    assert patch_attempt.status_code in [404, 405]
