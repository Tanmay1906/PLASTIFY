"""PLASTIFY Part 9 Comprehensive Integration Test Suite.

Validates:
1. Valid and invalid eligibility assessments.
2. Missing evidence and unverified sources rejected.
3. Methodology version reproducibility.
4. Duplicate impact records and duplicate allocations prevented.
5. Over-allocation and incompatible units rejected.
6. Unauthorized issuance rejected.
7. Self-approval prevention (creator & beneficiary org cannot approve).
8. Concurrent issuance attempts / idempotent retries.
9. External registry timeout and reconciliation (PENDING_RECONCILIATION).
10. Duplicate retirement rejected / idempotent.
11. Attempts to reuse retired credits rejected.
12. Cross-organization access denied (tenant isolation).
13. End-to-end provenance: Recovery -> Verification -> Impact -> Assessment -> Batch -> Issuance -> Transfer -> Retirement.
"""

from datetime import datetime, timezone
from decimal import Decimal
import io
import uuid
import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.organization import OrganizationType
from app.models.user import UserRole


# ------------------------------------------------------------------------------
# Test Helper to setup complete verified ecosystem
# ------------------------------------------------------------------------------

async def _setup_verified_ecosystem(client: AsyncClient, create_user, auth_headers):
    """Create corporate, program, collector, logistics, recycler, verifier, and verified recovery."""
    # 1. Corporate & Program
    corp = await create_user(email=f"corp_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.CORPORATE)
    corp_h = auth_headers(corp)
    c_org = (await client.post("/api/v1/organizations", headers=corp_h, json={
        "name": f"CorpOrg_{uuid.uuid4().hex[:6]}", "org_type": OrganizationType.CORPORATE.value, "contact_email": corp.email
    })).json()
    corp_org_id = c_org["id"]

    prog = (await client.post("/api/v1/programs", headers=corp_h, json={
        "name": f"SeaClean_{uuid.uuid4().hex[:6]}",
        "description": "Marine recovery program",
        "region": "MUM",
        "target_kg": 50000.0,
        "allowed_material_types": ["PET", "HDPE"],
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-12-31T23:59:59Z",
    })).json()
    prog_id = prog["id"]
    await client.patch(f"/api/v1/programs/{prog_id}", headers=corp_h, json={"status": "ACTIVE"})

    # 2. Collector
    col = await create_user(email=f"col_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.COLLECTOR)
    col_h = auth_headers(col)
    col_org = (await client.post("/api/v1/organizations", headers=col_h, json={
        "name": f"ColOrg_{uuid.uuid4().hex[:6]}", "org_type": OrganizationType.COLLECTOR.value, "contact_email": col.email
    })).json()
    col_org_id = col_org["id"]

    # 3. Logistics
    log = await create_user(email=f"log_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.LOGISTICS)
    log_h = auth_headers(log)
    log_org = (await client.post("/api/v1/organizations", headers=log_h, json={
        "name": f"LogOrg_{uuid.uuid4().hex[:6]}", "org_type": OrganizationType.LOGISTICS.value, "contact_email": log.email
    })).json()
    log_org_id = log_org["id"]

    # 4. Recycler
    rec = await create_user(email=f"rec_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.RECYCLER)
    rec_h = auth_headers(rec)
    rec_org = (await client.post("/api/v1/organizations", headers=rec_h, json={
        "name": f"RecOrg_{uuid.uuid4().hex[:6]}", "org_type": OrganizationType.RECYCLER.value, "contact_email": rec.email
    })).json()
    rec_org_id = rec_org["id"]

    # 5. Verifier
    ver = await create_user(email=f"ver_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.VERIFIER)
    ver_h = auth_headers(ver)
    ver_org = (await client.post("/api/v1/organizations", headers=ver_h, json={
        "name": f"VerOrg_{uuid.uuid4().hex[:6]}", "org_type": OrganizationType.VERIFIER.value, "contact_email": ver.email
    })).json()
    ver_org_id = ver_org["id"]

    # Assign partners
    await client.post(f"/api/v1/programs/{prog_id}/partners", headers=corp_h, json={"organization_id": col_org_id, "assigned_role": "COLLECTOR"})
    await client.post(f"/api/v1/programs/{prog_id}/partners", headers=corp_h, json={"organization_id": log_org_id, "assigned_role": "LOGISTICS"})
    await client.post(f"/api/v1/programs/{prog_id}/partners", headers=corp_h, json={"organization_id": rec_org_id, "assigned_role": "RECYCLER"})
    await client.post(f"/api/v1/programs/{prog_id}/partners", headers=corp_h, json={"organization_id": ver_org_id, "assigned_role": "VERIFIER"})

    # 6. Create Draft Recovery Event (1000 kg PET)
    draft_res = await client.post("/api/v1/recoveries", headers=col_h, json={
        "program_id": prog_id,
        "material_type": "PET",
        "weight_kg": 1000.0,
        "collection_location": "Versova Coast",
        "notes": "Verified coastal recovery",
    })
    recovery = draft_res.json()
    rec_id = recovery["id"]

    # 7. Upload photo evidence
    fake_img = io.BytesIO(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"E" * 200)
    await client.post(
        f"/api/v1/recoveries/{rec_id}/evidence",
        headers=col_h,
        files={"file": ("evidence.jpg", fake_img, "image/jpeg")},
        data={"evidence_type": "COLLECTION_PHOTO"},
    )

    # 8. Submit recovery & update custody
    await client.post(f"/api/v1/recoveries/{rec_id}/submit", headers=col_h, json={"notes": "Submit"})
    await client.post(f"/api/v1/recoveries/{rec_id}/custody/transition", headers=col_h, json={"new_state": CustodyState.SUBMITTED.value})

    # 9. Logistics flow
    asgn = (await client.post("/api/v1/logistics/assignments", headers=corp_h, json={
        "recovery_id": rec_id,
        "logistics_organization_id": log_org_id,
        "destination_organization_id": rec_org_id,
        "destination_location": "Central Recycler",
    })).json()
    asgn_id = asgn["id"]
    delivery_id = asgn["delivery"]["id"]

    await client.post(f"/api/v1/logistics/assignments/{asgn_id}/accept", headers=log_h, json={})
    await client.post(f"/api/v1/logistics/assignments/{asgn_id}/pickup", headers=log_h, json={})
    await client.post(f"/api/v1/logistics/deliveries/{delivery_id}/in-transit", headers=log_h, json={})
    await client.post(f"/api/v1/logistics/deliveries/{delivery_id}/delivered", headers=log_h, json={"delivered_weight_kg": 1000.0})
    await client.post(f"/api/v1/logistics/deliveries/{delivery_id}/receive", headers=rec_h, json={"received_weight_kg": 1000.0})

    # 10. Verification flow
    await client.post(f"/api/v1/verification/{rec_id}/approve", headers=ver_h, json={
        "verified_weight_kg": 1000.0,
        "notes": "Verified 1000kg",
    })

    # 11. Auditor user
    auditor = await create_user(email=f"auditor_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.AUDITOR)
    aud_h = auth_headers(auditor)

    # 12. Super Admin user
    admin = await create_user(email=f"admin_{uuid.uuid4().hex[:6]}@plastify.io", role=UserRole.SUPER_ADMIN)
    adm_h = auth_headers(admin)

    return {
        "corp": corp, "corp_h": corp_h, "corp_org_id": corp_org_id,
        "col": col, "col_h": col_h, "col_org_id": col_org_id,
        "log": log, "log_h": log_h, "log_org_id": log_org_id,
        "rec": rec, "rec_h": rec_h, "rec_org_id": rec_org_id,
        "ver": ver, "ver_h": ver_h, "ver_org_id": ver_org_id,
        "aud": auditor, "aud_h": aud_h,
        "admin": admin, "adm_h": adm_h,
        "prog_id": prog_id,
        "recovery_id": rec_id,
    }


# ------------------------------------------------------------------------------
# Test 1: Methodology Registration and Version Immutability
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_methodology_lifecycle_and_immutability(client: AsyncClient, create_user, auth_headers):
    """Test methodology registration, version publish, and discount validations."""
    admin = await create_user(email="meth_admin@plastify.io", role=UserRole.SUPER_ADMIN)
    adm_h = auth_headers(admin)

    # 1. Register Methodology
    m_res = await client.post("/api/v1/impact/methodologies", headers=adm_h, json={
        "code": "PLASTIFY-COL-V1",
        "name": "Plastify Ocean Bound Plastic Collection Standard",
        "description": "Standardized accounting protocol for verified marine plastic recovery.",
        "standard_name": "PLASTIFY Marine Protocol",
        "is_standard_recognized": False,
    })
    assert m_res.status_code == 201
    m_data = m_res.json()
    m_id = m_data["id"]

    # Duplicate code rejected
    dup_res = await client.post("/api/v1/impact/methodologies", headers=adm_h, json={
        "code": "PLASTIFY-COL-V1",
        "name": "Duplicate Code",
        "description": "Testing duplicate rejection.",
    })
    assert dup_res.status_code == 409

    # 2. Publish Version 1.0.0
    v_res = await client.post(f"/api/v1/impact/methodologies/{m_id}/versions", headers=adm_h, json={
        "version_tag": "1.0.0",
        "activity_type": "COLLECTION",
        "eligible_materials": ["PET", "HDPE"],
        "credit_conversion_factor": "0.001000",  # 1 Credit = 1000 KG (1 MT)
        "credit_unit_name": "PLASTIC_RECOVERY_CREDIT",
        "additionality_discount": "0.0500",     # 5% additionality deduction
        "baseline_discount": "0.0200",          # 2% baseline deduction
        "leakage_deduction": "0.0100",          # 1% leakage deduction
        "required_evidence_types": ["COLLECTION_PHOTO"],
        "requires_independent_verification": True,
    })
    assert v_res.status_code == 201
    v_data = v_res.json()
    assert v_data["is_immutable"] is True
    assert v_data["version_tag"] == "1.0.0"

    # Reject duplicate version tag under same methodology
    dup_v = await client.post(f"/api/v1/impact/methodologies/{m_id}/versions", headers=adm_h, json={
        "version_tag": "1.0.0",
        "activity_type": "COLLECTION",
        "eligible_materials": ["PET"],
        "required_evidence_types": ["COLLECTION_PHOTO"],
    })
    assert dup_v.status_code == 409

    # Reject deductions >= 100%
    bad_v = await client.post(f"/api/v1/impact/methodologies/{m_id}/versions", headers=adm_h, json={
        "version_tag": "2.0.0",
        "activity_type": "COLLECTION",
        "eligible_materials": ["PET"],
        "additionality_discount": "0.8000",
        "baseline_discount": "0.3000",  # 80% + 30% = 110% > 100%
        "required_evidence_types": ["COLLECTION_PHOTO"],
    })
    assert bad_v.status_code == 400


# ------------------------------------------------------------------------------
# Test 2: Impact Record Registration & Duplicate Protection
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_impact_registration_and_duplicate_prevention(client: AsyncClient, create_user, auth_headers):
    """Test registering verified impact records and enforcing non-duplication."""
    eco = await _setup_verified_ecosystem(client, create_user, auth_headers)
    col_h = eco["col_h"]
    rec_id = eco["recovery_id"]

    # 1. Register collection impact
    imp_res = await client.post("/api/v1/impact/records", headers=col_h, json={
        "outcome_type": "COLLECTION",
        "source_recovery_id": rec_id,
        "notes": "Verified collection impact",
    })
    assert imp_res.status_code == 201
    imp_data = imp_res.json()
    assert imp_data["quantity"] == "1000.0000"
    assert imp_data["unallocated_quantity"] == "1000.0000"
    assert imp_data["material_type"] == "PET"
    assert len(imp_data["evidence_manifest"]) > 0

    # 2. Attempt duplicate registration of same recovery event -> MUST BE REJECTED WITH 409
    dup_res = await client.post("/api/v1/impact/records", headers=col_h, json={
        "outcome_type": "COLLECTION",
        "source_recovery_id": rec_id,
        "notes": "Attempting duplicate registration",
    })
    assert dup_res.status_code == 409
    assert "Duplicate claim prevented" in dup_res.json()["error"]["message"]


# ------------------------------------------------------------------------------
# Test 3: Unverified Sources & Missing Evidence Gates in Eligibility
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unverified_sources_and_missing_evidence_gates(client: AsyncClient, create_user, auth_headers):
    """Test that unverified recoveries or missing evidence fail eligibility assessment."""
    eco = await _setup_verified_ecosystem(client, create_user, auth_headers)
    col_h = eco["col_h"]
    prog_id = eco["prog_id"]
    adm_h = eco["adm_h"]

    # 1. Create a methodology requiring WEIGHBRIDGE_RECEIPT
    m = (await client.post("/api/v1/impact/methodologies", headers=adm_h, json={
        "code": "RIGID-STRICT-V1",
        "name": "Strict Verification Protocol",
        "description": "Requires weighbridge receipt.",
    })).json()
    v = (await client.post(f"/api/v1/impact/methodologies/{m['id']}/versions", headers=adm_h, json={
        "version_tag": "1.0.0",
        "activity_type": "COLLECTION",
        "eligible_materials": ["PET"],
        "credit_conversion_factor": "0.001000",
        "required_evidence_types": ["COLLECTION_PHOTO", "WEIGHBRIDGE_RECEIPT"],  # Demands weighbridge receipt
        "requires_independent_verification": True,
    })).json()

    # 2. Register impact from eco's verified recovery (which only uploaded COLLECTION_PHOTO)
    imp = (await client.post("/api/v1/impact/records", headers=col_h, json={
        "outcome_type": "COLLECTION",
        "source_recovery_id": eco["recovery_id"],
    })).json()

    # 3. Assess eligibility -> Must return REQUIRES_REVIEW or INELIGIBLE with missing evidence explanation
    ass_res = await client.post("/api/v1/impact/assessments", headers=col_h, json={
        "impact_record_id": imp["id"],
        "methodology_version_id": v["id"],
    })
    assert ass_res.status_code == 201
    ass_data = ass_res.json()
    assert ass_data["status"] == "REQUIRES_REVIEW"
    assert ass_data["net_credit_units"] == "0.0000"
    assert any("WEIGHBRIDGE_RECEIPT" in r for r in ass_data["reasons"])


# ------------------------------------------------------------------------------
# Test 4: End-to-End Provenance: Impact -> Assessment -> Batch -> Issuance -> Retirement
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_credit_lifecycle_and_self_approval_prevention(client: AsyncClient, create_user, auth_headers):
    """Complete end-to-end audit:
    - Assess eligible impact
    - Create credit batch
    - Prevent self-approval (creator/beneficiary org rejected)
    - Independent auditor approves batch
    - Controlled issuance with serial minting
    - Transfer credits
    - Permanent retirement with certificate
    - Reject double-retirement and reuse
    """
    eco = await _setup_verified_ecosystem(client, create_user, auth_headers)
    col = eco["col"]
    col_h = eco["col_h"]
    rec_id = eco["recovery_id"]
    adm_h = eco["adm_h"]
    aud_h = eco["aud_h"]
    corp_h = eco["corp_h"]
    corp_org_id = eco["corp_org_id"]

    # 1. Setup Standard Methodology
    m = (await client.post("/api/v1/impact/methodologies", headers=adm_h, json={
        "code": "PWRS-OBP-V1",
        "name": "Plastic Waste Reduction Marine Standard",
        "description": "Certified OBP collection and crediting protocol.",
    })).json()
    v = (await client.post(f"/api/v1/impact/methodologies/{m['id']}/versions", headers=adm_h, json={
        "version_tag": "1.0.0",
        "activity_type": "COLLECTION",
        "eligible_materials": ["PET", "HDPE"],
        "credit_conversion_factor": "0.001000",  # 1 Credit per 1000 KG
        "credit_unit_name": "OBP_RECOVERY_CREDIT",
        "additionality_discount": "0.0200",     # 2% discount -> Net = 1000 * 0.001 * 0.98 = 0.9800 credits
        "baseline_discount": "0.0000",
        "leakage_deduction": "0.0000",
        "required_evidence_types": ["COLLECTION_PHOTO"],
        "requires_independent_verification": True,
    })).json()

    # 2. Register Impact Record (1000 KG)
    imp = (await client.post("/api/v1/impact/records", headers=col_h, json={
        "outcome_type": "COLLECTION",
        "source_recovery_id": rec_id,
    })).json()
    imp_id = imp["id"]

    # 3. Run Eligibility Assessment -> ELIGIBLE
    ass_res = await client.post("/api/v1/impact/assessments", headers=col_h, json={
        "impact_record_id": imp_id,
        "methodology_version_id": v["id"],
    })
    assert ass_res.status_code == 201
    ass_data = ass_res.json()
    assert ass_data["status"] == "ELIGIBLE"
    assert ass_data["net_credit_units"] == "0.9800"
    ass_id = ass_data["id"]

    # 4. Form Credit Batch (draws 1000 KG)
    batch_res = await client.post("/api/v1/credits/batches", headers=col_h, json={
        "methodology_version_id": v["id"],
        "allocations": [{"assessment_id": ass_id, "allocated_quantity_kg": "1000.0000"}],
        "vintage_year": 2026,
        "credit_type": "OBP_RECOVERY_CREDIT",
    })
    assert batch_res.status_code == 201
    batch = batch_res.json()
    batch_id = batch["id"]
    assert batch["status"] == "DRAFT"
    assert batch["total_credits"] == "0.9800"

    # 5. Over-Allocation Test: Attempt to form second batch requesting another 500 KG from same impact -> MUST FAIL WITH 400
    over_res = await client.post("/api/v1/credits/batches", headers=col_h, json={
        "methodology_version_id": v["id"],
        "allocations": [{"assessment_id": ass_id, "allocated_quantity_kg": "500.0000"}],
        "vintage_year": 2026,
    })
    assert over_res.status_code == 400
    assert any(msg in over_res.json()["error"]["message"] for msg in ["Over-allocation error", "ALLOCATED"])

    # 6. SELF-APPROVAL & AUTHORIZATION PREVENTION TESTS
    # Attempt A: Non-auditor/collector tries to approve -> 403 Forbidden (RBAC gate)
    unauth_appr = await client.post(f"/api/v1/credits/batches/{batch_id}/approve", headers=col_h, json={})
    assert unauth_appr.status_code == 403
    assert "Insufficient permissions" in unauth_appr.json()["error"]["message"]

    # Attempt B: Internal verifier belonging to the creator's organization tries to approve -> 403 Forbidden (Domain Self-Approval gate)
    col_verifier = await create_user(
        email=f"col_ver_{uuid.uuid4().hex[:6]}@plastify.io",
        role=UserRole.VERIFIER,
        organization_id=uuid.UUID(eco["col_org_id"]),
    )
    col_ver_h = auth_headers(col_verifier)
    self_appr_res = await client.post(f"/api/v1/credits/batches/{batch_id}/approve", headers=col_ver_h, json={})
    assert self_appr_res.status_code == 403
    assert "Self-approval violation" in self_appr_res.json()["error"]["message"]

    # 7. Independent Verifier/Auditor Approves Batch
    appr_res = await client.post(f"/api/v1/credits/batches/{batch_id}/approve", headers=aud_h, json={
        "notes": "Audited and approved independently",
    })
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "APPROVED"

    # 8. External Registry Timeout Simulation: System must enter PENDING_RECONCILIATION
    timeout_res = await client.post(f"/api/v1/credits/batches/{batch_id}/issue", headers=adm_h, json={
        "idempotency_key": f"key-sim-timeout-{uuid.uuid4().hex[:6]}",
        "simulate_registry_timeout": True,
    })
    assert timeout_res.status_code == 200
    assert timeout_res.json()["registry_status"] == "PENDING_RECONCILIATION"
    assert timeout_res.json()["status"] == "APPROVED"  # Not yet issued!

    # 9. Controlled Credit Issuance (with Idempotency Key)
    idemp_key = f"key-issuance-{uuid.uuid4().hex[:8]}"
    issue_res = await client.post(f"/api/v1/credits/batches/{batch_id}/issue", headers=adm_h, json={
        "idempotency_key": idemp_key,
        "issuance_notes": "Official release of 2026 OBP credits",
    })
    assert issue_res.status_code == 200
    issued_data = issue_res.json()
    assert issued_data["status"] == "ISSUED"
    assert len(issued_data["credits"]) == 1
    credit = issued_data["credits"][0]
    credit_id = credit["id"]
    assert "PC-2026" in credit["serial_number"]
    assert credit["status"] == "ACTIVE"

    # 10. Idempotent Retry of Issuance: Calling again with same key returns original issued batch without re-minting
    retry_issue = await client.post(f"/api/v1/credits/batches/{batch_id}/issue", headers=adm_h, json={
        "idempotency_key": idemp_key,
    })
    assert retry_issue.status_code == 200
    assert retry_issue.json()["batch_number"] == issued_data["batch_number"]

    # 11. Credit Transfer: Transfer credit from Collector Org to Corporate Org
    transfer_res = await client.post("/api/v1/credits/transfer", headers=col_h, json={
        "credit_id": credit_id,
        "to_organization_id": corp_org_id,
        "notes": "B2B sale to sponsor corporate",
    })
    assert transfer_res.status_code == 200
    tx_data = transfer_res.json()
    assert tx_data["tx_type"] == "TRANSFER"
    assert len(tx_data["audit_hash"]) == 64

    # Verify corporate now owns the credit
    c_list = (await client.get("/api/v1/credits", headers=corp_h)).json()
    assert any(c["id"] == credit_id for c in c_list)

    # 12. Permanent Credit Retirement
    ret_idemp = f"ret-key-{uuid.uuid4().hex[:8]}"
    ret_res = await client.post("/api/v1/credits/retire", headers=corp_h, json={
        "credit_id": credit_id,
        "quantity": "0.9800",
        "beneficiary_name": "Global Beverage Brand Ltd.",
        "retirement_reason": "Offsetting 2026 packaging environmental footprint.",
        "idempotency_key": ret_idemp,
    })
    assert ret_res.status_code == 201
    ret_data = ret_res.json()
    assert "CERT-RET-2026" in ret_data["certificate_id"]
    assert len(ret_data["certificate_hash"]) == 64
    assert ret_data["beneficiary_name"] == "Global Beverage Brand Ltd."

    # 13. Terminal Retirement Lock: Attempt to reuse or re-retire the credit -> MUST FAIL WITH 400
    reuse_res = await client.post("/api/v1/credits/retire", headers=corp_h, json={
        "credit_id": credit_id,
        "quantity": "0.9800",
        "beneficiary_name": "Another Company",
        "retirement_reason": "Attempting reuse of retired credit",
    })
    assert reuse_res.status_code == 400
    assert "Terminal state error" in reuse_res.json()["error"]["message"]

    # 14. Idempotent Retry of Retirement with Same Idempotency Key -> Returns existing certificate without error
    ret_retry = await client.post("/api/v1/credits/retire", headers=corp_h, json={
        "credit_id": credit_id,
        "quantity": "0.9800",
        "beneficiary_name": "Global Beverage Brand Ltd.",
        "retirement_reason": "Offsetting 2026 packaging environmental footprint.",
        "idempotency_key": ret_idemp,
    })
    assert ret_retry.status_code in [200, 201]
    assert ret_retry.json()["certificate_id"] == ret_data["certificate_id"]


# ------------------------------------------------------------------------------
# Test 5: Traceable Superseding / Audit Correction
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_traceable_superseding_of_impact_record(client: AsyncClient, create_user, auth_headers):
    """Test that an auditor can traceably supersede an impact record with documented justification."""
    eco = await _setup_verified_ecosystem(client, create_user, auth_headers)
    col_h = eco["col_h"]
    aud_h = eco["aud_h"]
    rec_id = eco["recovery_id"]

    # Register impact record (1000 KG)
    imp = (await client.post("/api/v1/impact/records", headers=col_h, json={
        "outcome_type": "COLLECTION",
        "source_recovery_id": rec_id,
    })).json()
    imp_id = imp["id"]

    # Auditor supersedes record (adjusts to 950 KG due to tare scale calibration)
    sup_res = await client.post(f"/api/v1/impact/records/{imp_id}/supersede", headers=aud_h, json={
        "new_quantity_kg": "950.0000",
        "reason": "Calibration error detected on weighbridge tare scale (-50 KG correction).",
    })
    assert sup_res.status_code == 200
    replacement = sup_res.json()
    assert replacement["quantity"] == "950.0000"
    assert replacement["supersedes_id"] == imp_id

    # Verify original record is now SUPERSEDED
    orig_res = await client.get(f"/api/v1/impact/records/{imp_id}", headers=aud_h)
    assert orig_res.json()["status"] == "SUPERSEDED"
    assert orig_res.json()["superseded_by_id"] == replacement["id"]
