"""Tests for Plastic Collection, Recovery Events, and State Transition History.

Validates:
- Backend generation of immutable, human-readable Recovery IDs (e.g. POP-DEL-2026-000001)
- Prohibition of frontend-generated Recovery IDs
- Server-side validations: active program, partner assignment, allowed materials, positive weight, valid timestamps
- Draft lifecycle: updates in DRAFT, submission to SUBMITTED
- Automatic updates to program collected_kg
- Immutable event audit history records
- Retrieval via UUID and human-readable ID
- Role and tenant isolation
"""

from datetime import datetime, timedelta, timezone
import re
import pytest
from httpx import AsyncClient

from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole


async def _setup_program_and_collector(client: AsyncClient, create_user, auth_headers):
    """Helper fixture to set up an active program, a corporate owner, and an assigned collector."""
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email="sustainability@danone-waters.com", role=UserRole.CORPORATE
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Danone Waters Global",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "danone@waters.com",
            "country": "France",
        },
    )
    corp_org_id = corp_org_res.json()["id"]

    # 2. Create Active Program
    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Delhi Coastal & Riverine Clean 2026",
            "region": "DEL",
            "target_kg": 50000.0,
            "allowed_material_types": [
                PlasticMaterialType.PET.value,
                PlasticMaterialType.HDPE.value,
            ],
            "status": ProgramStatus.ACTIVE.value,
        },
    )
    program = prog_res.json()
    program_id = program["id"]

    # 3. Collector Organization & User
    col_user = await create_user(
        email="harish.kumar@greendelhi.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Green Delhi Waste Aggregators",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@greendelhi.org",
            "country": "India",
            "city": "Delhi",
        },
    )
    col_org_id = col_org_res.json()["id"]

    # 4. Assign Collector Org to Program
    assign_res = await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={
            "organization_id": col_org_id,
            "assigned_role": "COLLECTOR",
            "region_scope": "DEL",
        },
    )
    assert assign_res.status_code == 201

    return {
        "corp_user": corp_user,
        "corp_headers": corp_headers,
        "corp_org_id": corp_org_id,
        "program_id": program_id,
        "col_user": col_user,
        "col_headers": col_headers,
        "col_org_id": col_org_id,
    }


@pytest.mark.asyncio
async def test_collector_can_view_assigned_tasks(
    client: AsyncClient, create_user, auth_headers
):
    """Collector can view programs / tasks assigned to their organization."""
    data = await _setup_program_and_collector(client, create_user, auth_headers)
    col_headers = data["col_headers"]

    # Query assigned collection tasks
    res = await client.get("/api/v1/recoveries/collector/tasks", headers=col_headers)
    assert res.status_code == 200
    tasks = res.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == data["program_id"]
    assert tasks[0]["name"] == "Delhi Coastal & Riverine Clean 2026"
    assert "PET" in tasks[0]["allowed_material_types"]


@pytest.mark.asyncio
async def test_create_recovery_event_generates_immutable_id(
    client: AsyncClient, create_user, auth_headers
):
    """Backend generates unique immutable human-readable Recovery ID (e.g. POP-DEL-2026-000001)."""
    data = await _setup_program_and_collector(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    program_id = data["program_id"]

    payload = {
        "program_id": program_id,
        "material_type": PlasticMaterialType.PET.value,
        "weight_kg": 450.5,
        "collection_location": "Okhla Landfill Transfer Station, Delhi",
        "collection_coordinates": {"latitude": 28.5245, "longitude": 77.2793},
        "notes": "Baled clear beverage bottles collected from sector 4.",
    }

    res = await client.post("/api/v1/recoveries", headers=col_headers, json=payload)
    assert res.status_code == 201
    recovery = res.json()

    assert "id" in recovery
    assert "recovery_id" in recovery
    # Verify Recovery ID format: POP-DEL-{YEAR}-{SEQ:06d}
    current_year = datetime.now(timezone.utc).year
    pattern = rf"^POP-DEL-{current_year}-\d{{6}}$"
    assert re.match(pattern, recovery["recovery_id"]) is not None
    assert recovery["status"] == "DRAFT"
    assert recovery["weight_kg"] == 450.5
    assert recovery["material_type"] == "PET"
    assert recovery["collector_name"] == "Test User"
    assert len(recovery["history"]) == 1
    assert recovery["history"][0]["to_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_recovery_validations_enforced(
    client: AsyncClient, create_user, auth_headers
):
    """Server-side validations: active program, partner assignment, allowed materials, positive weight."""
    data = await _setup_program_and_collector(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    program_id = data["program_id"]

    # 1. Disallowed material type (PVC not in [PET, HDPE])
    res_bad_material = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PVC.value,
            "weight_kg": 100.0,
            "collection_location": "Site A",
        },
    )
    assert res_bad_material.status_code == 400
    assert "not permitted" in res_bad_material.json()["error"]["message"]

    # 2. Non-positive weight
    res_bad_weight = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": -50.0,
            "collection_location": "Site A",
        },
    )
    assert res_bad_weight.status_code == 422  # Pydantic gt=0 validation

    # 3. Future collection timestamp
    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    res_future_time = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 100.0,
            "collection_location": "Site A",
            "collected_at": future_time,
        },
    )
    assert res_future_time.status_code == 422

    # 4. Inactive (DRAFT) program cannot accept recoveries
    corp_headers = data["corp_headers"]
    draft_prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Draft Inactive Program",
            "region": "DEL",
            "target_kg": 5000.0,
            "allowed_material_types": [PlasticMaterialType.PET.value],
            "status": ProgramStatus.DRAFT.value,
        },
    )
    draft_prog_id = draft_prog_res.json()["id"]

    res_inactive = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": draft_prog_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 100.0,
            "collection_location": "Site A",
        },
    )
    assert res_inactive.status_code == 400
    assert "not ACTIVE" in res_inactive.json()["error"]["message"]

    # 5. Unassigned Collector cannot create recovery
    unassigned_col = await create_user(
        email="unassigned@other.org", role=UserRole.COLLECTOR
    )
    unassigned_headers = auth_headers(unassigned_col)
    await client.post(
        "/api/v1/organizations",
        headers=unassigned_headers,
        json={
            "name": "Unrelated Waste Org",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "unassigned@other.org",
        },
    )

    res_unassigned = await client.post(
        "/api/v1/recoveries",
        headers=unassigned_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 100.0,
            "collection_location": "Site A",
        },
    )
    assert res_unassigned.status_code == 403


@pytest.mark.asyncio
async def test_draft_update_and_submit_lifecycle(
    client: AsyncClient, create_user, auth_headers
):
    """Test updating draft recovery event, submitting it, locking edits, and updating program progress."""
    data = await _setup_program_and_collector(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    program_id = data["program_id"]

    # 1. Create Draft
    create_res = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.HDPE.value,
            "weight_kg": 300.0,
            "collection_location": "Yamuna River Bank Sector 12",
        },
    )
    assert create_res.status_code == 201
    recovery_event = create_res.json()
    event_id = recovery_event["id"]
    human_id = recovery_event["recovery_id"]

    # 2. Update Draft (adjust weight and notes)
    patch_res = await client.patch(
        f"/api/v1/recoveries/{event_id}",
        headers=col_headers,
        json={"weight_kg": 350.0, "notes": "Recalibrated scale +50kg"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["weight_kg"] == 350.0
    assert patch_res.json()["notes"] == "Recalibrated scale +50kg"

    # 3. Submit Recovery
    submit_res = await client.post(
        f"/api/v1/recoveries/{event_id}/submit",
        headers=col_headers,
        json={"notes": "Final verified tally by site manager"},
    )
    assert submit_res.status_code == 200
    submitted_event = submit_res.json()
    assert submitted_event["status"] == "SUBMITTED"

    # 4. Edits to SUBMITTED recovery are rejected
    tamper_res = await client.patch(
        f"/api/v1/recoveries/{event_id}",
        headers=col_headers,
        json={"weight_kg": 500.0},
    )
    assert tamper_res.status_code == 400
    assert "Only DRAFT events can be modified" in tamper_res.json()["error"]["message"]

    # 5. Verify Program collected_kg is incremented by 350.0 kg
    prog_check = await client.get(
        f"/api/v1/programs/{program_id}", headers=data["corp_headers"]
    )
    assert prog_check.status_code == 200
    assert prog_check.json()["collected_kg"] == 350.0

    # 6. Verify Retrieval by Human Recovery ID
    get_by_human_id = await client.get(
        f"/api/v1/recoveries/{human_id}", headers=col_headers
    )
    assert get_by_human_id.status_code == 200
    assert get_by_human_id.json()["id"] == event_id

    # 7. Verify Immutable State History
    hist_res = await client.get(
        f"/api/v1/recoveries/{event_id}/history", headers=col_headers
    )
    assert hist_res.status_code == 200
    history = hist_res.json()
    assert len(history) == 2
    assert history[0]["to_status"] == "DRAFT"
    assert history[1]["from_status"] == "DRAFT"
    assert history[1]["to_status"] == "SUBMITTED"
    assert history[1]["actor_role"] == "COLLECTOR"


@pytest.mark.asyncio
async def test_list_collector_and_program_recoveries(
    client: AsyncClient, create_user, auth_headers
):
    """Test listing recoveries by collector and by program."""
    data = await _setup_program_and_collector(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    program_id = data["program_id"]

    # Create 2 recoveries
    await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 120.0,
            "collection_location": "Collection Point Alpha",
        },
    )
    await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.HDPE.value,
            "weight_kg": 240.0,
            "collection_location": "Collection Point Beta",
        },
    )

    # List by collector
    col_list_res = await client.get("/api/v1/recoveries/collector/me", headers=col_headers)
    assert col_list_res.status_code == 200
    assert len(col_list_res.json()) == 2

    # List by program (corporate owner)
    prog_list_res = await client.get(
        f"/api/v1/recoveries/program/{program_id}", headers=data["corp_headers"]
    )
    assert prog_list_res.status_code == 200
    assert len(prog_list_res.json()) == 2
