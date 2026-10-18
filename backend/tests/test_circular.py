"""Tests for PLASTIFY Circular Economy Engines (Part 8).

Validates:
1. Recycling Engine:
   - Incoming verified materials discovery for certified recyclers
   - Creation of MaterialBatch drawing verified recovery events
   - Mass conservation invariant: recycled_output + residual <= input_weight
   - Rejection of impossible mass accounting (output + residual > input)
   - Processing yield tracking and metadata recording
   - Upload of digital processing evidence (scales, lab assays)
   - Batch completion and Digital Material Passport generation
   - Custody state advancement to PROCESSED

2. Upcycling Engine:
   - Secondary raw material availability discovery
   - Upcycler material allocation from completed MaterialBatches
   - Rejection of over-allocation (> unallocated recycled output)
   - Upcycling production batch creation
   - Quality verification, grading, and specifications recording
   - Upload of manufacturing evidence
   - Batch completion and commercial Product registration

3. Digital Product Passport (DPP):
   - Automatic generation of QR-ready public passport identifier
   - Public unauthenticated resolution of ProductPassport
   - Full provenance chain tracing: Product -> Upcycling Batch -> Material Batch -> Recovery Event(s)
   - Segregated mass accounting verification:
     collected, delivered, verified, recycled_output, upcycled_material, residual

4. RBAC & Multi-Tenant Isolation:
   - Recycler A cannot access or modify Recycler B's processing batch
   - Upcycler cannot tamper with recycler batches
   - Unauthorized roles rejected
"""

import io
from typing import Any, Dict, List
import uuid
import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.evidence import EvidenceType
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole
from app.models.verification import VerificationDecision


# ------------------------------------------------------------------------------
# Test Fixture / Supply Chain Setup Helper
# ------------------------------------------------------------------------------

async def _setup_circular_ecosystem(
    client: AsyncClient, create_user, auth_headers
) -> Dict[str, Any]:
    """Sets up an end-to-end verified recovery event ready for industrial recycling."""
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email="esg@danone-circular.com", role=UserRole.CORPORATE
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Danone Global Circular",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "esg@danone-circular.com",
        },
    )
    corp_org_id = corp_org_res.json()["id"]

    # 2. Corporate Program (PET)
    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Mahim Bay Coastal Clean 2026",
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

    # 3. Collector Org & User
    col_user = await create_user(
        email="lead@mumbai-ocean.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Mumbai Ocean Cleaners",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@mumbai-ocean.org",
        },
    )
    col_org_id = col_org_res.json()["id"]

    # 4. Logistics Org & User
    log_user = await create_user(
        email="ops@greentransit.in", role=UserRole.LOGISTICS
    )
    log_headers = auth_headers(log_user)
    log_org_res = await client.post(
        "/api/v1/organizations",
        headers=log_headers,
        json={
            "name": "Green Eco Transit",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "ops@greentransit.in",
        },
    )
    log_org_id = log_org_res.json()["id"]

    # 5. Recycler Org & User (Recycler 1)
    rec_user = await create_user(
        email="plant.manager@ecopolymers.com", role=UserRole.RECYCLER
    )
    rec_headers = auth_headers(rec_user)
    rec_org_res = await client.post(
        "/api/v1/organizations",
        headers=rec_headers,
        json={
            "name": "EcoPolymers Industrial Recycling",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "plant@ecopolymers.com",
        },
    )
    rec_org_id = rec_org_res.json()["id"]

    # 6. Second Recycler Org & User (For Isolation / Multi-tenancy tests)
    rec2_user = await create_user(
        email="manager@rival-recycling.com", role=UserRole.RECYCLER
    )
    rec2_headers = auth_headers(rec2_user)
    rec2_org_res = await client.post(
        "/api/v1/organizations",
        headers=rec2_headers,
        json={
            "name": "Rival Polymers Ltd",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "contact@rival-recycling.com",
        },
    )
    rec2_org_id = rec2_org_res.json()["id"]

    # 7. Upcycler Org & User
    upc_user = await create_user(
        email="design@circulardesignlab.com", role=UserRole.UPCYCLER
    )
    upc_headers = auth_headers(upc_user)
    upc_org_res = await client.post(
        "/api/v1/organizations",
        headers=upc_headers,
        json={
            "name": "Circular Design Lab Studio",
            "org_type": OrganizationType.UPCYCLER.value,
            "contact_email": "hello@circulardesignlab.com",
        },
    )
    upc_org_id = upc_org_res.json()["id"]

    # 8. Verifier Org & User
    ver_user = await create_user(
        email="lead.verifier@sgs-circular.com", role=UserRole.VERIFIER
    )
    ver_headers = auth_headers(ver_user)
    ver_org_res = await client.post(
        "/api/v1/organizations",
        headers=ver_headers,
        json={
            "name": "SGS Circular Assurance",
            "org_type": OrganizationType.VERIFIER.value,
            "contact_email": "audits@sgs-circular.com",
        },
    )
    ver_org_id = ver_org_res.json()["id"]

    # Assign partners to program
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
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": ver_org_id, "assigned_role": "VERIFIER"},
    )

    # 9. Create Recovery Event (100 kg PET)
    rec_ev_res = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 100.0,
            "collection_location": "Versova Beachfront Intake Hub, Mumbai",
            "collection_coordinates": {"lat": 19.131, "lng": 72.815},
            "notes": "Recovered ocean-bound PET bottles from Mahim shoreline",
        },
    )
    assert rec_ev_res.status_code == 201, rec_ev_res.text
    recovery = rec_ev_res.json()
    recovery_id = recovery["id"]

    # Upload Collection Evidence
    fake_photo = io.BytesIO(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"A" * 200)
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("shoreline_pet.jpg", fake_photo, "image/jpeg")},
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value, "notes": "Baled PET photo"},
    )

    # Submit Recovery Event
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

    # 10. Logistics Lifecycle: Assign -> Accept -> Pickup -> In Transit -> Deliver -> Receive
    asgn_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=corp_headers,
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": log_org_id,
            "destination_organization_id": rec_org_id,
            "destination_location": "EcoPolymers Intake Unit",
        },
    )
    assert asgn_res.status_code == 201, asgn_res.text
    assignment = asgn_res.json()
    assignment_id = assignment["id"]
    delivery_id = assignment["delivery"]["id"]

    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/accept",
        headers=log_headers,
        json={},
    )
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=log_headers,
        json={"vehicle_number": "MH-02-EE-1984"},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=log_headers,
        json={"tracking_number": "TRK-BOM-8831"},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=log_headers,
        json={"delivered_weight_kg": 99.8},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=rec_headers,
        json={"received_weight_kg": 99.8, "receipt_notes": "Weighbridge tare verified"},
    )

    # 11. Verifier approves recovery
    ver_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=ver_headers,
        json={
            "verified_weight_kg": 99.8,
            "checklist": {
                "photo_evidence_matched": True,
                "weight_slips_reconciled": True,
                "gps_location_valid": True,
            },
            "notes": "Photographs, weighbridge slips, GPS and Sentinel risk clear. Verified.",
        },
    )
    assert ver_res.status_code == 200, ver_res.text

    return {
        "corp_user": corp_user,
        "corp_headers": corp_headers,
        "col_user": col_user,
        "col_headers": col_headers,
        "rec_user": rec_user,
        "rec_headers": rec_headers,
        "rec2_user": rec2_user,
        "rec2_headers": rec2_headers,
        "upc_user": upc_user,
        "upc_headers": upc_headers,
        "ver_user": ver_user,
        "ver_headers": ver_headers,
        "recovery_id": recovery_id,
        "recovery_code": recovery["recovery_id"],
        "verified_weight_kg": 99.8,
    }


# ------------------------------------------------------------------------------
# RECYCLING ENGINE TESTS
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recycler_incoming_verified_materials_discovery(
    client: AsyncClient, create_user, auth_headers
):
    """Certified recyclers must discover verified raw recovery events delivered to their facility."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    res = await client.get("/api/v1/recycling/incoming-materials", headers=rec_headers)
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) >= 1
    target = next((item for item in items if item["recovery_id"] == eco["recovery_id"]), None)
    assert target is not None
    assert target["material_type"] == PlasticMaterialType.PET.value
    assert target["collected_weight_kg"] == 100.0
    assert target["verified_weight_kg"] == 99.8
    assert target["available_weight_kg"] == 99.8


@pytest.mark.asyncio
async def test_create_material_batch_success(
    client: AsyncClient, create_user, auth_headers
):
    """Recycler creates an industrial processing batch drawing verified material."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    payload = {
        "material_type": PlasticMaterialType.PET.value,
        "source_items": [
            {
                "recovery_id": eco["recovery_id"],
                "allocated_weight_kg": 99.8,
            }
        ],
        "notes": "Batch #1: Optical sorting, cold wash, flaking process",
    }

    res = await client.post("/api/v1/recycling/batches", headers=rec_headers, json=payload)
    assert res.status_code == 201, res.text
    batch = res.json()
    assert batch["batch_id"].startswith("MB-")
    assert batch["material_type"] == PlasticMaterialType.PET.value
    assert batch["input_weight_kg"] == 99.8
    assert batch["recycled_output_kg"] == 0.0
    assert batch["residual_kg"] == 0.0
    assert batch["status"] == "CREATED"
    assert len(batch["items"]) == 1
    assert batch["items"][0]["recovery_id"] == eco["recovery_id"]
    assert batch["items"][0]["allocated_weight_kg"] == 99.8


@pytest.mark.asyncio
async def test_mass_conservation_invariant_impossible_accounting_rejected(
    client: AsyncClient, create_user, auth_headers
):
    """Business Invariant: recycled_output + residual <= input_weight.

    Attempting impossible mass accounting (output + residual > input) must raise HTTP 400.
    """
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    # 1. Create batch with 99.8 kg input
    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [
                {"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}
            ],
        },
    )
    batch_id = batch_res.json()["id"]

    # 2. Attempt impossible mass accounting: 90.0 kg output + 15.0 kg residual = 105.0 kg > 99.8 kg input
    impossible_payload = {
        "recycled_output_kg": 90.0,
        "residual_kg": 15.0,
        "notes": "Impossible mass generation",
    }
    violation_res = await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec_headers,
        json=impossible_payload,
    )
    assert violation_res.status_code == 400
    err_data = violation_res.json()
    assert "Impossible mass accounting" in err_data["error"]["message"]


@pytest.mark.asyncio
async def test_update_valid_processing_yields(
    client: AsyncClient, create_user, auth_headers
):
    """Record valid mass yields where recycled_output + residual <= input_weight."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    # Create batch
    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [
                {"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}
            ],
        },
    )
    batch_id = batch_res.json()["id"]

    # Valid yields: 85.0 kg rPET pellets + 12.5 kg residual/sludge = 97.5 kg <= 99.8 kg
    valid_payload = {
        "recycled_output_kg": 85.0,
        "residual_kg": 12.5,
        "verification_reference": "LAB-TEST-PET-2026-9921",
        "notes": "Hot wash, decontamination, extruding to rPET pellets",
    }
    update_res = await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec_headers,
        json=valid_payload,
    )
    assert update_res.status_code == 200, update_res.text
    updated = update_res.json()
    assert updated["recycled_output_kg"] == 85.0
    assert updated["residual_kg"] == 12.5
    assert updated["yield_percentage"] == round((85.0 / 99.8) * 100, 2)
    assert updated["status"] == "IN_PROCESSING"
    assert updated["verification_reference"] == "LAB-TEST-PET-2026-9921"


@pytest.mark.asyncio
async def test_upload_processing_evidence(
    client: AsyncClient, create_user, auth_headers
):
    """Recycler uploads photographic or lab assay evidence to the recycling batch."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [
                {"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}
            ],
        },
    )
    batch_id = batch_res.json()["id"]

    fake_lab_report = io.BytesIO(b"%PDF-1.4 Fake Lab Assay Spectrometry Report " + b"X" * 100)
    ev_res = await client.post(
        f"/api/v1/recycling/batches/{batch_id}/evidence",
        headers=rec_headers,
        files={"file": ("rpet_purity_test.pdf", fake_lab_report, "application/pdf")},
        data={"evidence_type": "LAB_ANALYSIS", "notes": "99.9% polymer purity certified"},
    )
    assert ev_res.status_code == 201, ev_res.text
    ev = ev_res.json()
    assert ev["evidence_type"] == "LAB_ANALYSIS"
    assert ev["original_filename"] == "rpet_purity_test.pdf"
    assert "sha256_hash" in ev


@pytest.mark.asyncio
async def test_complete_processing_and_issue_material_passport(
    client: AsyncClient, create_user, auth_headers
):
    """Completing a recycling batch transitions custody to PROCESSED and issues a Material Passport."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]

    # 1. Create batch
    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [
                {"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}
            ],
        },
    )
    batch_id = batch_res.json()["id"]

    # 2. Record yields (85.0 kg rPET + 10.0 kg residual <= 99.8 kg)
    await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec_headers,
        json={"recycled_output_kg": 85.0, "residual_kg": 10.0},
    )

    # 3. Complete processing
    comp_res = await client.post(
        f"/api/v1/recycling/batches/{batch_id}/complete",
        headers=rec_headers,
    )
    assert comp_res.status_code == 200, comp_res.text
    completed = comp_res.json()
    assert completed["status"] == "COMPLETED"
    assert completed["material_passport_code"] is not None
    passport_code = completed["material_passport_code"]
    assert passport_code.startswith("MP-")

    # 4. Verify public passport lookup endpoint
    pub_res = await client.get(f"/api/v1/passports/material/{passport_code}")
    assert pub_res.status_code == 200, pub_res.text
    passport = pub_res.json()
    assert passport["passport_code"] == passport_code
    assert passport["material_type"] == PlasticMaterialType.PET.value
    assert passport["input_weight_kg"] == 99.8
    assert passport["recycled_output_kg"] == 85.0
    assert passport["residual_kg"] == 10.0
    assert passport["yield_percentage"] == round((85.0 / 99.8) * 100, 2)


# ------------------------------------------------------------------------------
# UPCYCLING ENGINE TESTS
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upcycling_material_availability_and_allocation(
    client: AsyncClient, create_user, auth_headers
):
    """Upcyclers query available secondary raw materials and allocate from completed batches."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]
    upc_headers = eco["upc_headers"]

    # 1. Recycler produces 85.0 kg of recycled PET pellets
    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [
                {"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}
            ],
        },
    )
    batch_id = batch_res.json()["id"]
    await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec_headers,
        json={"recycled_output_kg": 85.0, "residual_kg": 10.0},
    )
    await client.post(
        f"/api/v1/recycling/batches/{batch_id}/complete",
        headers=rec_headers,
    )

    # 2. Upcycler checks available materials
    avail_res = await client.get("/api/v1/upcycling/available-materials", headers=upc_headers)
    assert avail_res.status_code == 200, avail_res.text
    materials = avail_res.json()
    assert len(materials) >= 1
    mat_match = next((m for m in materials if m["material_batch_id"] == batch_id), None)
    assert mat_match is not None
    assert mat_match["recycled_output_kg"] == 85.0
    assert mat_match["available_weight_kg"] == 85.0

    # 3. Upcycler attempts over-allocation (> 85.0 kg) -> Must fail with 400
    over_res = await client.post(
        "/api/v1/upcycling/batches",
        headers=upc_headers,
        json={
            "product_type": "HIGH_PERFORMANCE_RUNNING_SHOES",
            "material_allocations": [
                {"material_batch_id": batch_id, "allocated_weight_kg": 100.0}
            ],
        },
    )
    assert over_res.status_code == 400
    err_data = over_res.json()
    assert "Over-allocation" in err_data["error"]["message"]

    # 4. Upcycler allocates valid amount (50.0 kg)
    upc_batch_res = await client.post(
        "/api/v1/upcycling/batches",
        headers=upc_headers,
        json={
            "product_type": "HIGH_PERFORMANCE_RUNNING_SHOES",
            "material_allocations": [
                {"material_batch_id": batch_id, "allocated_weight_kg": 50.0}
            ],
            "notes": "Upcycling into recycled high-tensile yarn for shoe uppers",
        },
    )
    assert upc_batch_res.status_code == 201, upc_batch_res.text
    upc_batch = upc_batch_res.json()
    assert upc_batch["batch_id"].startswith("UPC-")
    assert upc_batch["total_input_material_kg"] == 50.0
    assert upc_batch["status"] == "CREATED"


@pytest.mark.asyncio
async def test_upcycling_quality_verification_and_production_evidence(
    client: AsyncClient, create_user, auth_headers
):
    """Record QA inspection specifications and production evidence on an upcycling batch."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]
    upc_headers = eco["upc_headers"]

    # Setup completed recycling batch
    b_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [{"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}],
        },
    )
    b_id = b_res.json()["id"]
    await client.patch(
        f"/api/v1/recycling/batches/{b_id}/processing",
        headers=rec_headers,
        json={"recycled_output_kg": 85.0, "residual_kg": 5.0},
    )
    await client.post(f"/api/v1/recycling/batches/{b_id}/complete", headers=rec_headers)

    # Create upcycling batch
    upc_res = await client.post(
        "/api/v1/upcycling/batches",
        headers=upc_headers,
        json={
            "product_type": "CIRCULAR_TEXTILE_JACKET",
            "material_allocations": [{"material_batch_id": b_id, "allocated_weight_kg": 40.0}],
        },
    )
    assert upc_res.status_code == 201, upc_res.text
    upc_id = upc_res.json()["id"]

    # 1. Update QA
    qa_res = await client.patch(
        f"/api/v1/upcycling/batches/{upc_id}/quality",
        headers=upc_headers,
        json={
            "quality_verified": True,
            "quality_rating": "GRADE_A_PREMIUM",
            "quality_notes": "Tensile strength 450 MPa, zero color degradation, certified OEKO-TEX Standard 100",
        },
    )
    assert qa_res.status_code == 200, qa_res.text
    assert qa_res.json()["quality_rating"] == "GRADE_A_PREMIUM"
    assert qa_res.json()["quality_verified"] is True

    # 2. Upload Production Evidence
    fake_loom_img = io.BytesIO(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"L" * 250)
    ev_res = await client.post(
        f"/api/v1/upcycling/batches/{upc_id}/evidence",
        headers=upc_headers,
        files={"file": ("spinning_loom_production.jpg", fake_loom_img, "image/jpeg")},
        data={"evidence_type": "SPINNING_PROOF", "notes": "Automated circular yarn spinning loom run"},
    )
    assert ev_res.status_code == 201, ev_res.text
    assert ev_res.json()["evidence_type"] == "SPINNING_PROOF"


@pytest.mark.asyncio
async def test_complete_upcycling_and_register_product_with_dpp(
    client: AsyncClient, create_user, auth_headers
):
    """Complete upcycling production batch, register Product, and verify public ProductPassport."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec_headers = eco["rec_headers"]
    upc_headers = eco["upc_headers"]

    # 1. Recycling batch setup
    b_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [{"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}],
        },
    )
    b_id = b_res.json()["id"]
    await client.patch(
        f"/api/v1/recycling/batches/{b_id}/processing",
        headers=rec_headers,
        json={"recycled_output_kg": 85.0, "residual_kg": 10.0},
    )
    await client.post(f"/api/v1/recycling/batches/{b_id}/complete", headers=rec_headers)

    # 2. Upcycling batch creation & completion
    upc_res = await client.post(
        "/api/v1/upcycling/batches",
        headers=upc_headers,
        json={
            "product_type": "OCEAN_THREAD_JACKET",
            "material_allocations": [{"material_batch_id": b_id, "allocated_weight_kg": 60.0}],
        },
    )
    assert upc_res.status_code == 201, upc_res.text
    upc_id = upc_res.json()["id"]

    complete_res = await client.post(
        f"/api/v1/upcycling/batches/{upc_id}/complete",
        headers=upc_headers,
        json={"quantity_produced": 120, "notes": "Production run complete: 120 jackets"},
    )
    assert complete_res.status_code == 200, complete_res.text

    # 3. Register Product with DPP
    prod_res = await client.post(
        f"/api/v1/upcycling/batches/{upc_id}/products",
        headers=upc_headers,
        json={
            "name": "Plastify Ultra-Light Ocean Jacket",
            "sku": "SKU-PLOJ-2026-M",
            "description": "High performance waterproof jacket crafted from 100% verified ocean-bound plastic.",
            "recycled_content_percentage": 94.5,
            "weight_per_unit_kg": 0.5,
            "metadata": {
                "color": "Ocean Abyss Blue",
                "waterproof_rating": "20,000 mm",
                "recycled_plastic_origin": "Mahim Bay, Mumbai",
            },
        },
    )
    assert prod_res.status_code == 201, prod_res.text
    prod = prod_res.json()
    assert prod["name"] == "Plastify Ultra-Light Ocean Jacket"
    assert prod["sku"] == "SKU-PLOJ-2026-M"
    assert prod["passport_id"] is not None
    passport_id = prod["passport_id"]
    assert passport_id.startswith("PP-")

    # --------------------------------------------------------------------------
    # 4. PUBLIC DPP RESOLUTION & FULL PROVENANCE VERIFICATION
    # --------------------------------------------------------------------------
    pub_res = await client.get(f"/api/v1/passports/product/{passport_id}")
    assert pub_res.status_code == 200, pub_res.text
    provenance = pub_res.json()

    # Verify root product data
    assert provenance["passport_id"] == passport_id
    assert provenance["product"]["name"] == "Plastify Ultra-Light Ocean Jacket"
    assert provenance["product"]["sku"] == "SKU-PLOJ-2026-M"

    # Verify Upcycling Batch Link
    assert provenance["upcycling_batch"]["id"] == upc_id
    assert provenance["upcycling_batch"]["product_type"] == "OCEAN_THREAD_JACKET"

    # Verify Material Batches Link
    mat_batches = provenance["material_batches"]
    assert len(mat_batches) >= 1
    assert mat_batches[0]["id"] == b_id
    assert mat_batches[0]["material_type"] == PlasticMaterialType.PET.value

    # Verify Source Recoveries Link (Full provenance tracing back to ocean collection)
    recoveries = provenance["source_recoveries"]
    assert len(recoveries) >= 1
    assert recoveries[0]["recovery_id"] == eco["recovery_id"]
    assert recoveries[0]["recovery_human_id"] == eco["recovery_code"]

    # Verify Segregated Physical Mass Accounting Metrics
    mass = provenance["mass_accounting"]
    assert mass["collected_weight_kg"] == 100.0
    assert mass["delivered_weight_kg"] == 99.8
    assert mass["verified_weight_kg"] == 99.8
    assert mass["recycled_output_kg"] == 85.0
    assert mass["residual_kg"] == 10.0
    assert mass["upcycled_material_kg"] == 60.0
    # Mass conservation verified: all stages distinct and strictly tracked
    assert mass["recycled_output_kg"] + mass["residual_kg"] <= mass["verified_weight_kg"]


# ------------------------------------------------------------------------------
# MULTI-TENANT ISOLATION & RBAC TESTS
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_tenant_isolation_and_rbac(
    client: AsyncClient, create_user, auth_headers
):
    """Ensure organization isolation: Recycler B cannot mutate Recycler A's batch, etc."""
    eco = await _setup_circular_ecosystem(client, create_user, auth_headers)
    rec1_headers = eco["rec_headers"]
    rec2_headers = eco["rec2_headers"]
    upc_headers = eco["upc_headers"]

    # Recycler 1 creates a batch
    batch_res = await client.post(
        "/api/v1/recycling/batches",
        headers=rec1_headers,
        json={
            "material_type": PlasticMaterialType.PET.value,
            "source_items": [{"recovery_id": eco["recovery_id"], "allocated_weight_kg": 99.8}],
        },
    )
    batch_id = batch_res.json()["id"]

    # Recycler 2 tries to update Recycler 1's batch yields -> 403 Forbidden
    rival_update = await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec2_headers,
        json={"recycled_output_kg": 80.0, "residual_kg": 10.0},
    )
    assert rival_update.status_code == 403

    # Upcycler tries to mutate recycling batch -> 403 Forbidden
    upcycler_tamper = await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=upc_headers,
        json={"recycled_output_kg": 80.0, "residual_kg": 10.0},
    )
    assert upcycler_tamper.status_code == 403

    # Recycler 1 can update their own batch
    own_update = await client.patch(
        f"/api/v1/recycling/batches/{batch_id}/processing",
        headers=rec1_headers,
        json={"recycled_output_kg": 80.0, "residual_kg": 10.0},
    )
    assert own_update.status_code == 200
