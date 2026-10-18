"""Tests for PLASTIFY Logistics and Delivery Engine.

Validates:
- Complete physical movement workflow:
  Recovery Event -> Pickup Assignment -> Pickup Accepted -> Picked Up -> In Transit -> Delivered -> Recycler Received
- Strict server-side transition validations:
  - Cannot deliver before pickup (400)
  - Cannot receive before delivery (400)
  - Cannot transition out-of-order (400)
- Multi-tenant organization boundaries:
  - Carrier cannot accept/modify another carrier's assignment (403)
  - Recycler cannot confirm another recycler's delivery (403)
  - Unauthorized user cannot view delivery history (403)
- Configurable weight tolerance evaluation:
  - Within tolerance (e.g. 100 KG -> 99.5 KG) -> PASS
  - Outside tolerance (e.g. 100 KG -> 90.0 KG) -> FLAG_FOR_REVIEW (never automated fraud)
- Delivery evidence association
- Historical immutability and chain of custody integration
"""

import io
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.evidence import EvidenceType
from app.models.logistics import (
    AssignmentStatus,
    DeliveryStatus,
    WeightToleranceStatus,
)
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole


async def _setup_logistics_ecosystem(client: AsyncClient, create_user, auth_headers):
    """Sets up a complete circular logistics network."""
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email="sustainability@danone-circular.com", role=UserRole.CORPORATE
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Danone Circular Network",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "sustainability@danone-circular.com",
        },
    )
    corp_org_id = corp_org_res.json()["id"]

    # 2. Program
    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Mumbai Marine Plastic Initiative 2026",
            "region": "BOM",
            "target_kg": 50000.0,
            "allowed_material_types": [
                PlasticMaterialType.PET.value,
                PlasticMaterialType.HDPE.value,
            ],
            "status": ProgramStatus.ACTIVE.value,
        },
    )
    program_id = prog_res.json()["id"]

    # 3. Collector Org and User
    col_user = await create_user(
        email="collector@mumbai-clean.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Mumbai Coastal Cleaners Coop",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@mumbai-clean.org",
        },
    )
    col_org_id = col_org_res.json()["id"]

    # 4. Logistics Org A (Assigned Carrier)
    log_user = await create_user(
        email="dispatch@blueocean-logistics.com", role=UserRole.LOGISTICS
    )
    log_headers = auth_headers(log_user)
    log_org_res = await client.post(
        "/api/v1/organizations",
        headers=log_headers,
        json={
            "name": "Blue Ocean Green Logistics",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "dispatch@blueocean-logistics.com",
        },
    )
    log_org_id = log_org_res.json()["id"]

    # 5. Logistics Org B (Unrelated Stranger Carrier)
    stranger_log_user = await create_user(
        email="intruder@rival-freight.com", role=UserRole.LOGISTICS
    )
    stranger_log_headers = auth_headers(stranger_log_user)
    stranger_log_org_res = await client.post(
        "/api/v1/organizations",
        headers=stranger_log_headers,
        json={
            "name": "Rival Freight Services",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "intruder@rival-freight.com",
        },
    )
    stranger_log_org_id = stranger_log_org_res.json()["id"]

    # 6. Recycler Org A (Designated Destination Facility)
    rec_user = await create_user(
        email="intake@cleantech-recycling.com", role=UserRole.RECYCLER
    )
    rec_headers = auth_headers(rec_user)
    rec_org_res = await client.post(
        "/api/v1/organizations",
        headers=rec_headers,
        json={
            "name": "CleanTech Circular Polymers",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "intake@cleantech-recycling.com",
        },
    )
    rec_org_id = rec_org_res.json()["id"]

    # 7. Recycler Org B (Unrelated Recycler)
    stranger_rec_user = await create_user(
        email="unrelated@other-recycler.com", role=UserRole.RECYCLER
    )
    stranger_rec_headers = auth_headers(stranger_rec_user)
    stranger_rec_org_res = await client.post(
        "/api/v1/organizations",
        headers=stranger_rec_headers,
        json={
            "name": "Unrelated Waste Processing Ltd",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "unrelated@other-recycler.com",
        },
    )
    stranger_rec_org_id = stranger_rec_org_res.json()["id"]

    # Assign operational partners to program
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": col_org_id, "assigned_role": "COLLECTOR"},
    )
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": log_org_id, "assigned_role": "LOGISTICS"},
    )
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": rec_org_id, "assigned_role": "RECYCLER"},
    )

    # 8. Create and Submit Recovery Event (100.0 KG PET)
    rec_event_res = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 100.0,
            "collection_location": "Versova Beachfront Intake Hub, Mumbai",
        },
    )
    recovery = rec_event_res.json()
    recovery_id = recovery["id"]

    # Submit recovery event
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/submit",
        headers=col_headers,
        json={"notes": "100 KG ocean bound PET packaged into standard shipping bales"},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=col_headers,
        json={"new_state": CustodyState.SUBMITTED.value},
    )

    return {
        "program_id": program_id,
        "recovery_id": recovery_id,
        "human_recovery_id": recovery["recovery_id"],
        "corp_headers": corp_headers,
        "col_headers": col_headers,
        "col_org_id": col_org_id,
        "log_headers": log_headers,
        "log_org_id": log_org_id,
        "stranger_log_headers": stranger_log_headers,
        "stranger_log_org_id": stranger_log_org_id,
        "rec_headers": rec_headers,
        "rec_org_id": rec_org_id,
        "stranger_rec_headers": stranger_rec_headers,
        "stranger_rec_org_id": stranger_rec_org_id,
    }


# ==============================================================================
# 1. Valid Lifecycle Test
# ==============================================================================


@pytest.mark.asyncio
async def test_valid_logistics_and_delivery_lifecycle(
    client: AsyncClient, create_user, auth_headers
):
    """Test full sequential lifecycle:
    Recovery Submitted -> Assign Logistics -> Accept Assignment -> Mark Picked Up ->
    Mark In Transit -> Mark Delivered -> Recycler Confirms Receipt (PASS tolerance) -> View History.
    """
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Step 1: Corporate assigns Logistics partner
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
            "destination_location": "CleanTech Polymer Processing Unit 2",
            "notes": "Fragile clean sorted PET bales",
        },
    )
    assert assign_res.status_code == 201
    assignment = assign_res.json()
    assignment_id = assignment["id"]
    delivery_id = assignment["delivery"]["id"]

    assert assignment["status"] == "ASSIGNED"
    assert assignment["logistics_organization_id"] == eco["log_org_id"]
    assert assignment["destination_organization_id"] == eco["rec_org_id"]
    assert assignment["delivery"]["status"] == "PENDING"
    assert assignment["delivery"]["expected_weight_kg"] == 100.0

    # Step 2: Logistics carrier accepts assignment
    accept_res = await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=eco["log_headers"],
        json={"notes": "Driver and flatbed vehicle assigned"},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "ACCEPTED"

    # Step 3: Logistics marks pickup completed
    pickup_res = await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=eco["log_headers"],
        json={
            "vehicle_number": "MH-02-EE-1984",
            "notes": "Bales verified on collector platform scale",
        },
    )
    assert pickup_res.status_code == 200
    pickup_data = pickup_res.json()
    assert pickup_data["status"] == "PICKED_UP"
    assert pickup_data["delivery"]["status"] == "PICKED_UP"
    assert pickup_data["delivery"]["vehicle_number"] == "MH-02-EE-1984"

    # Step 4: Logistics marks shipment in transit
    transit_res = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["log_headers"],
        json={
            "tracking_number": "TRK-BOM-2026-9921",
            "current_location": "Western Express Highway Transit Corridor",
            "notes": "En route to processing facility",
        },
    )
    assert transit_res.status_code == 200
    transit_data = transit_res.json()
    assert transit_data["status"] == "IN_TRANSIT"
    assert transit_data["tracking_number"] == "TRK-BOM-2026-9921"

    # Step 5: Logistics marks shipment delivered
    deliv_res = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=eco["log_headers"],
        json={
            "delivered_weight_kg": 100.0,
            "notes": "Truck arrived at CleanTech intake gate #3",
        },
    )
    assert deliv_res.status_code == 200
    deliv_data = deliv_res.json()
    assert deliv_data["status"] == "DELIVERED"
    assert deliv_data["delivered_weight_kg"] == 100.0
    assert deliv_data["delivery_timestamp"] is not None

    # Step 6: Recycler confirms receipt (Expected = 100.0 KG, Received = 99.5 KG)
    # Difference: 0.5 KG (0.5% discrepancy) <= 2.0% tolerance -> PASS!
    receipt_res = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=eco["rec_headers"],
        json={
            "received_weight_kg": 99.5,
            "receipt_notes": "Weighbridge gross tare confirmed. Clean bales accepted.",
        },
    )
    assert receipt_res.status_code == 200
    receipt_data = receipt_res.json()
    assert receipt_data["status"] == "RECEIVED"
    assert receipt_data["received_weight_kg"] == 99.5
    assert receipt_data["weight_discrepancy_kg"] == 0.5
    assert receipt_data["weight_tolerance_status"] == "PASS"

    # Step 7: View delivery history and full chain of custody timeline
    history_res = await client.get(
        f"/api/v1/logistics/deliveries/{delivery_id}/history",
        headers=eco["corp_headers"],
    )
    assert history_res.status_code == 200
    history = history_res.json()
    assert history["delivery"]["id"] == delivery_id
    assert history["delivery"]["status"] == "RECEIVED"

    # Verify chronological chain-of-custody event progression
    states = [ev["new_state"] for ev in history["custody_events"]]
    assert "SUBMITTED" in states
    assert "PICKUP_ASSIGNED" in states
    assert "PICKED_UP" in states
    assert "IN_TRANSIT" in states
    assert "DELIVERED" in states
    assert "RECEIVED" in states


# ==============================================================================
# 2. Invalid State Transitions Server-Side Validation
# ==============================================================================


@pytest.mark.asyncio
async def test_invalid_transitions_rejected_server_side(
    client: AsyncClient, create_user, auth_headers
):
    """Server-side security rejects invalid transitions:
    - Cannot deliver before pickup
    - Cannot receive before delivery
    - Cannot mark in-transit before pickup
    - Cannot assign unsubmitted draft recovery event
    """
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Create assignment
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
        },
    )
    assignment = assign_res.json()
    assignment_id = assignment["id"]
    delivery_id = assignment["delivery"]["id"]

    # 1. Attempt to mark DELIVERED before pickup has occurred!
    early_deliver = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=eco["log_headers"],
        json={"delivered_weight_kg": 100.0},
    )
    assert early_deliver.status_code == 400
    assert "before pickup" in early_deliver.json()["error"]["message"]

    # 2. Attempt to RECEIVE before delivery has occurred!
    early_receive = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=eco["rec_headers"],
        json={"received_weight_kg": 100.0},
    )
    assert early_receive.status_code == 400
    assert "before shipment has been delivered" in early_receive.json()["error"]["message"]

    # 3. Attempt to mark IN_TRANSIT before pickup has occurred!
    early_transit = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["log_headers"],
        json={"tracking_number": "FAKE-TRK"},
    )
    assert early_transit.status_code == 400
    assert "before pickup" in early_transit.json()["error"]["message"]

    # 4. Attempt to assign an unsubmitted draft recovery event
    draft_res = await client.post(
        "/api/v1/recoveries",
        headers=eco["col_headers"],
        json={
            "program_id": eco["program_id"],
            "material_type": PlasticMaterialType.HDPE.value,
            "weight_kg": 250.0,
            "collection_location": "Bandra Reclamation, Mumbai",
        },
    )
    draft_recovery_id = draft_res.json()["id"]

    assign_draft = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": draft_recovery_id,
            "logistics_organization_id": eco["log_org_id"],
        },
    )
    assert assign_draft.status_code == 400
    assert "must be SUBMITTED" in assign_draft.json()["error"]["message"]

    # 5. Attempt to double-assign the already assigned recovery event
    double_assign = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
        },
    )
    assert double_assign.status_code == 400
    assert "already assigned" in double_assign.json()["error"]["message"]


# ==============================================================================
# 3. Multi-Tenant Organization Boundaries and Unauthorized Operations
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthorized_operations_and_organization_boundaries(
    client: AsyncClient, create_user, auth_headers
):
    """Users cannot modify another organization's delivery or access private history."""
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Assign to Carrier A (log_headers) and Recycler A (rec_headers)
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
        },
    )
    assignment = assign_res.json()
    assignment_id = assignment["id"]
    delivery_id = assignment["delivery"]["id"]

    # 1. Carrier B (stranger) attempts to accept Carrier A's assignment -> 403 Forbidden!
    hijack_accept = await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=eco["stranger_log_headers"],
        json={"notes": "Rival carrier trying to take shipment"},
    )
    assert hijack_accept.status_code == 403
    assert "assigned logistics organization" in hijack_accept.json()["error"]["message"]

    # Carrier A legitimately accepts & picks up
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=eco["log_headers"],
        json={"vehicle_number": "MH-01-A-1000"},
    )

    # 2. Carrier B attempts to mark Carrier A's delivery as in-transit -> 403 Forbidden!
    hijack_transit = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["stranger_log_headers"],
        json={"tracking_number": "ILLEGAL-TAG"},
    )
    assert hijack_transit.status_code == 403

    # Carrier A marks in transit and delivered
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["log_headers"],
        json={"tracking_number": "LEGIT-TRK"},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=eco["log_headers"],
        json={"delivered_weight_kg": 100.0},
    )

    # 3. Recycler B (stranger) attempts to confirm receipt of shipment destined for Recycler A -> 403 Forbidden!
    hijack_receipt = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=eco["stranger_rec_headers"],
        json={"received_weight_kg": 100.0},
    )
    assert hijack_receipt.status_code == 403
    assert "designated recipient recycling organization" in hijack_receipt.json()["error"]["message"]

    # 4. Stranger carrier attempts to view delivery history -> 403 Forbidden!
    snoop_history = await client.get(
        f"/api/v1/logistics/deliveries/{delivery_id}/history",
        headers=eco["stranger_log_headers"],
    )
    assert snoop_history.status_code == 403


# ==============================================================================
# 4. Weight Tolerance and Discrepancy Evaluation
# ==============================================================================


@pytest.mark.asyncio
async def test_weight_discrepancy_and_tolerance_evaluation(
    client: AsyncClient, create_user, auth_headers
):
    """Weight tolerance evaluation:
    - Expected = 100.0 KG, Received = 90.0 KG (10.0% discrepancy > 2.0% tolerance).
    - Status evaluates to FLAG_FOR_REVIEW.
    - System does not automatically accuse of fraud; delivery still completes with review flag.
    """
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Assign, Accept, Pickup, Transit, Deliver
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
        },
    )
    assignment_id = assign_res.json()["id"]
    delivery_id = assign_res.json()["delivery"]["id"]

    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=eco["log_headers"],
        json={"delivered_weight_kg": 100.0},
    )

    # Recycler confirms receipt with significant weight shortfall (90.0 KG received vs 100.0 KG expected)
    receipt_res = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=eco["rec_headers"],
        json={
            "received_weight_kg": 90.0,
            "receipt_notes": "Weighbridge shows 90.0 KG. 10 KG shortfall detected.",
        },
    )
    assert receipt_res.status_code == 200
    data = receipt_res.json()

    assert data["status"] == "RECEIVED"
    assert data["delivered_weight_kg"] == 100.0
    assert data["received_weight_kg"] == 90.0
    assert data["weight_discrepancy_kg"] == 10.0
    assert data["weight_tolerance_status"] == "FLAG_FOR_REVIEW"
    assert "FLAG_FOR_REVIEW" != "FRAUD"  # Not labeled fraud
    assert "Flagged for human verification review" in data["receipt_notes"]


# ==============================================================================
# 5. Delivery Evidence and Historical Immutability
# ==============================================================================


@pytest.mark.asyncio
async def test_delivery_evidence_and_immutability(
    client: AsyncClient, create_user, auth_headers
):
    """Verify delivery evidence attachment and tamper-proof historical immutability."""
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # 1. Upload evidence file to recovery event first
    evidence_res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=eco["col_headers"],
        files={"file": ("waybill.pdf", io.BytesIO(b"%PDF-1.5 waybill test"), "application/pdf")},
        data={"evidence_type": EvidenceType.DELIVERY_PROOF.value, "notes": "Official waybill"},
    )
    assert evidence_res.status_code == 201
    evidence_id = evidence_res.json()["id"]

    # 2. Assign and progress to delivered with evidence_id
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
        },
    )
    assignment_id = assign_res.json()["id"]
    delivery_id = assign_res.json()["delivery"]["id"]

    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=eco["log_headers"],
        json={},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=eco["log_headers"],
        json={},
    )
    deliv_res = await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=eco["log_headers"],
        json={"delivered_weight_kg": 100.0, "evidence_ids": [evidence_id]},
    )
    assert deliv_res.status_code == 200
    delivery = deliv_res.json()
    assert len(delivery["evidence_records"]) == 1
    assert delivery["evidence_records"][0]["evidence_id"] == evidence_id

    # 3. Immutability: Normal users cannot delete or patch historical deliveries
    del_attempt = await client.delete(
        f"/api/v1/logistics/deliveries/{delivery_id}",
        headers=eco["log_headers"],
    )
    assert del_attempt.status_code in [404, 405]

    patch_attempt = await client.patch(
        f"/api/v1/logistics/deliveries/{delivery_id}",
        headers=eco["log_headers"],
        json={"notes": "Attempt to erase discrepancy"},
    )
    assert patch_attempt.status_code in [404, 405]


# ==============================================================================
# 6. List Available Pickup Assignments
# ==============================================================================


@pytest.mark.asyncio
async def test_list_available_pickup_assignments(
    client: AsyncClient, create_user, auth_headers
):
    """Logistics partner lists available pickup tasks."""
    eco = await _setup_logistics_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Before assignment: 0 assignments for Carrier A
    list_before = await client.get(
        "/api/v1/logistics/assignments/available",
        headers=eco["log_headers"],
    )
    assert list_before.status_code == 200
    assert len(list_before.json()) == 0

    # Create assignment for Carrier A
    await client.post(
        "/api/v1/logistics/assignments",
        headers=eco["corp_headers"],
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": eco["log_org_id"],
            "destination_organization_id": eco["rec_org_id"],
        },
    )

    # Carrier A now sees 1 available pickup assignment
    list_after = await client.get(
        "/api/v1/logistics/assignments/available",
        headers=eco["log_headers"],
    )
    assert list_after.status_code == 200
    available = list_after.json()
    assert len(available) == 1
    assert available[0]["recovery_id"] == recovery_id
    assert available[0]["status"] == "ASSIGNED"

    # Stranger Carrier B does NOT see Carrier A's private assignment
    stranger_list = await client.get(
        "/api/v1/logistics/assignments/available",
        headers=eco["stranger_log_headers"],
    )
    assert stranger_list.status_code == 200
    assert len(stranger_list.json()) == 0
