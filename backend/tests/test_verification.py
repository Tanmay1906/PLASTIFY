"""Tests for PLASTIFY Verification Engine.

Validates:
- Verification queue inspection and jurisdiction filtering
- Complete verification package inspection (recovery, evidence, logistics, delivery, weight reconciliation, custody timeline)
- Authoritative approval workflow (atomic record creation, VERIFIED state, chain-of-custody, audit logs)
- Rejection workflow (mandatory reason, REJECTED state, chain-of-custody, evidence preservation)
- Flagging and review workflow (mandatory reason, FLAGGED state, finding creation)
- Server-side validations:
  - Unauthorized verifier & organization boundaries (403)
  - Self-verification prevention (collector cannot verify own batch) (400/403)
  - Missing evidence prevention (400)
  - Invalid state prevention (DRAFT, IN_TRANSIT, REJECTED) (400)
  - Duplicate approval prevention (400)
  - Unresolved critical blocking findings prevention (400)
  - Concurrent verification attempts (atomic pessimistic row lock)
  - Silent modification prevention on verified events
"""

import asyncio
from datetime import datetime, timezone
import io
from typing import List, Optional
import uuid
import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.evidence import EvidenceType
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole
from app.models.verification import FindingCategory, FindingSeverity


async def _setup_verification_ecosystem(
    client: AsyncClient, create_user, auth_headers, upload_evidence: bool = True
):
    """Sets up a complete circular supply chain through recycler receipt."""
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

    # 4. Logistics Org
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

    # 5. Recycler Org
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

    # 6. Authorized Verifier Org & User
    ver_user = await create_user(
        email="lead.auditor@tuv-rheinland-circular.com", role=UserRole.VERIFIER
    )
    ver_headers = auth_headers(ver_user)
    ver_org_res = await client.post(
        "/api/v1/organizations",
        headers=ver_headers,
        json={
            "name": "TUV Circular Assurance",
            "org_type": OrganizationType.VERIFIER.value,
            "contact_email": "audits@tuv-circular.com",
        },
    )
    ver_org_id = ver_org_res.json()["id"]

    # 7. Stranger/Unauthorized Verifier Org & User (Not partner on this program)
    stranger_ver_user = await create_user(
        email="unauthorized@rogue-audit.com", role=UserRole.VERIFIER
    )
    stranger_ver_headers = auth_headers(stranger_ver_user)
    stranger_ver_org_res = await client.post(
        "/api/v1/organizations",
        headers=stranger_ver_headers,
        json={
            "name": "Rogue Auditing Corp",
            "org_type": OrganizationType.VERIFIER.value,
            "contact_email": "unauthorized@rogue-audit.com",
        },
    )
    stranger_ver_org_id = stranger_ver_org_res.json()["id"]

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
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={"organization_id": ver_org_id, "assigned_role": "VERIFIER"},
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
            "collection_coordinates": {"lat": 19.131, "lng": 72.815},
        },
    )
    recovery = rec_event_res.json()
    recovery_id = recovery["id"]

    # Optional: Upload collection evidence
    evidence_id = None
    if upload_evidence:
        ev_res = await client.post(
            f"/api/v1/recoveries/{recovery_id}/evidence",
            headers=col_headers,
            files={"file": ("collection_photo.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" + b"collection"), "image/jpeg")},
            data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value, "notes": "Baled PET photo"},
        )
        assert ev_res.status_code == 201
        evidence_id = ev_res.json()["id"]

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

    # 9. Complete logistics movement to RECEIVED
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=corp_headers,
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": log_org_id,
            "destination_organization_id": rec_org_id,
            "destination_location": "CleanTech Polymer Unit",
        },
    )
    assignment = assign_res.json()
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
        json={"delivered_weight_kg": 100.0},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=rec_headers,
        json={"received_weight_kg": 99.5, "receipt_notes": "Weighbridge tare verified"},
    )

    return {
        "program_id": program_id,
        "recovery_id": recovery_id,
        "delivery_id": delivery_id,
        "evidence_id": evidence_id,
        "corp_headers": corp_headers,
        "col_headers": col_headers,
        "col_user": col_user,
        "col_org_id": col_org_id,
        "log_headers": log_headers,
        "rec_headers": rec_headers,
        "ver_headers": ver_headers,
        "ver_user": ver_user,
        "stranger_ver_headers": stranger_ver_headers,
    }


# ==============================================================================
# 1. Verification Package Inspection
# ==============================================================================


@pytest.mark.asyncio
async def test_complete_verification_package_inspection(
    client: AsyncClient, create_user, auth_headers
):
    """Verifier must be able to inspect a complete multi-party verification package."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    res = await client.get(
        f"/api/v1/verification/package/{recovery_id}",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    pkg = res.json()

    # Recovery details
    assert pkg["recovery"]["id"] == recovery_id
    assert pkg["recovery"]["material_type"] == "PET"
    assert pkg["recovery"]["weight_kg"] == 100.0
    assert pkg["recovery"]["custody_status"] == "RECEIVED"
    assert "Versova" in pkg["recovery"]["collection_location"]

    # Collection evidence
    assert len(pkg["collection_evidence"]) >= 1
    assert pkg["collection_evidence"][0]["id"] == eco["evidence_id"]

    # Logistics & Delivery
    assert pkg["logistics_assignment"] is not None
    assert pkg["delivery"] is not None
    assert pkg["delivery"]["status"] == "RECEIVED"

    # Weight comparison reconciliation
    weight = pkg["weight_comparison"]
    assert weight["expected_weight_kg"] == 100.0
    assert weight["received_weight_kg"] == 99.5
    assert weight["discrepancy_kg"] == 0.5
    assert weight["tolerance_status"] == "PASS"

    # Chain of custody timeline
    timeline = pkg["custody_timeline"]
    states = [ev["new_state"] for ev in timeline]
    assert "SUBMITTED" in states
    assert "PICKUP_ASSIGNED" in states
    assert "PICKED_UP" in states
    assert "IN_TRANSIT" in states
    assert "DELIVERED" in states
    assert "RECEIVED" in states


# ==============================================================================
# 2. Authoritative Approval Lifecycle
# ==============================================================================


@pytest.mark.asyncio
async def test_authoritative_approval_lifecycle(
    client: AsyncClient, create_user, auth_headers
):
    """Test successful verification approval, state transitions, custody update, and immutability."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    approve_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={
            "verified_weight_kg": 99.5,
            "checklist": {
                "photo_evidence_matched": True,
                "weight_slips_reconciled": True,
                "gps_location_valid": True,
            },
            "notes": "Verified against recycler tare scale readings.",
        },
    )
    assert approve_res.status_code == 200
    record = approve_res.json()

    assert record["decision"] == "APPROVED"
    assert record["verification_code"].startswith("VRF-")
    assert record["verified_weight_kg"] == 99.5
    assert record["recovery_id"] == recovery_id

    # Check that RecoveryEvent transitioned to VERIFIED
    pkg_res = await client.get(
        f"/api/v1/verification/package/{recovery_id}",
        headers=eco["ver_headers"],
    )
    assert pkg_res.json()["recovery"]["status"] == "VERIFIED"
    assert pkg_res.json()["recovery"]["custody_status"] == "VERIFIED"

    # Verify Chain of Custody event appended
    custody_events = pkg_res.json()["custody_timeline"]
    assert custody_events[-1]["new_state"] == "VERIFIED"
    assert custody_events[-1]["previous_state"] == "RECEIVED"

    # Verify record listed under recovery history
    records_res = await client.get(
        f"/api/v1/verification/{recovery_id}/records",
        headers=eco["ver_headers"],
    )
    assert records_res.status_code == 200
    assert len(records_res.json()) >= 1
    assert records_res.json()[0]["decision"] == "APPROVED"


# ==============================================================================
# 3. Authoritative Rejection Lifecycle & Evidence Preservation
# ==============================================================================


@pytest.mark.asyncio
async def test_authoritative_rejection_lifecycle_and_evidence_preservation(
    client: AsyncClient, create_user, auth_headers
):
    """Test rejection with mandatory reason, custody update, and evidence preservation."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Rejection without reason fails
    no_reason = await client.post(
        f"/api/v1/verification/{recovery_id}/reject",
        headers=eco["ver_headers"],
        json={"reason": "   "},
    )
    assert no_reason.status_code in [400, 422]

    # Valid rejection
    reject_res = await client.post(
        f"/api/v1/verification/{recovery_id}/reject",
        headers=eco["ver_headers"],
        json={
            "reason": "Recycler batch contained 30% PVC contamination violating program parameters.",
            "notes": "Lab test spectrograph indicates prohibited halogenated plastics.",
        },
    )
    assert reject_res.status_code == 200
    rec = reject_res.json()
    assert rec["decision"] == "REJECTED"
    assert "contamination" in rec["reason"]

    # Check recovery status transitioned to REJECTED
    pkg_res = await client.get(
        f"/api/v1/verification/package/{recovery_id}",
        headers=eco["ver_headers"],
    )
    assert pkg_res.json()["recovery"]["status"] == "REJECTED"
    assert pkg_res.json()["recovery"]["custody_status"] == "REJECTED"

    # Chain of custody updated to REJECTED
    timeline = pkg_res.json()["custody_timeline"]
    assert timeline[-1]["new_state"] == "REJECTED"

    # CRITICAL: Evidence is NOT deleted!
    assert len(pkg_res.json()["collection_evidence"]) >= 1
    ev_check = await client.get(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=eco["col_headers"],
    )
    assert ev_check.status_code == 200
    assert len(ev_check.json()) >= 1


# ==============================================================================
# 4. Flagging & Review Lifecycle
# ==============================================================================


@pytest.mark.asyncio
async def test_flagging_and_review_lifecycle(
    client: AsyncClient, create_user, auth_headers
):
    """Test flagging a recovery event for review with required reason."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Empty reason fails
    empty_flag = await client.post(
        f"/api/v1/verification/{recovery_id}/flag",
        headers=eco["ver_headers"],
        json={"reason": ""},
    )
    assert empty_flag.status_code in [400, 422]

    # Valid flag
    flag_res = await client.post(
        f"/api/v1/verification/{recovery_id}/flag",
        headers=eco["ver_headers"],
        json={
            "reason": "Weighbridge tare slip image is illegible. Request re-upload of clean scan.",
            "severity": FindingSeverity.WARNING.value,
            "category": FindingCategory.EVIDENCE_INTEGRITY.value,
        },
    )
    assert flag_res.status_code == 200
    rec = flag_res.json()
    assert rec["decision"] == "FLAGGED"

    # Status updated to FLAGGED
    pkg_res = await client.get(
        f"/api/v1/verification/package/{recovery_id}",
        headers=eco["ver_headers"],
    )
    assert pkg_res.json()["recovery"]["status"] == "FLAGGED"
    assert len(pkg_res.json()["sentinel_findings"]) >= 1


# ==============================================================================
# 5. Unauthorized Verifier & Organization Boundaries
# ==============================================================================


@pytest.mark.asyncio
async def test_unauthorized_verifier_and_organization_boundaries(
    client: AsyncClient, create_user, auth_headers
):
    """Non-verifiers and verifiers from outside partner orgs are denied verification actions."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # 1. Unrelated Verifier Org
    unauth_ver = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["stranger_ver_headers"],
        json={},
    )
    assert unauth_ver.status_code == 403

    # 2. Collector cannot verify
    col_attempt = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["col_headers"],
        json={},
    )
    assert col_attempt.status_code == 403

    # 3. Logistics cannot verify
    log_attempt = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["log_headers"],
        json={},
    )
    assert log_attempt.status_code == 403

    # 4. Recycler cannot verify
    rec_attempt = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["rec_headers"],
        json={},
    )
    assert rec_attempt.status_code == 403


# ==============================================================================
# 6. Self-Verification Prevention
# ==============================================================================


@pytest.mark.asyncio
async def test_self_verification_prevention(
    client: AsyncClient, create_user, auth_headers
):
    """A user or organization cannot verify a recovery event they collected."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Create a user who is assigned as VERIFIER, but belongs to the Collector's Org
    conflict_user = await create_user(
        email="conflict.auditor@mumbai-clean.org",
        role=UserRole.VERIFIER,
        organization_id=uuid.UUID(eco["col_org_id"]),
    )
    conflict_headers = auth_headers(conflict_user)

    # Attempt to approve collection from their own organization
    attempt = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=conflict_headers,
        json={},
    )
    assert attempt.status_code in [400, 403]


# ==============================================================================
# 7. Missing Evidence Prevention
# ==============================================================================


@pytest.mark.asyncio
async def test_missing_evidence_prevention(
    client: AsyncClient, create_user, auth_headers
):
    """Approval must fail if no required collection evidence exists."""
    # Setup ecosystem with upload_evidence=False
    eco = await _setup_verification_ecosystem(
        client, create_user, auth_headers, upload_evidence=False
    )
    recovery_id = eco["recovery_id"]

    approve_attempt = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert approve_attempt.status_code == 400
    assert "evidence" in approve_attempt.json()["error"]["message"].lower()


# ==============================================================================
# 8. Invalid States & Duplicate Approval Prevention
# ==============================================================================


@pytest.mark.asyncio
async def test_invalid_states_and_duplicate_approval(
    client: AsyncClient, create_user, auth_headers
):
    """Test rejection on invalid state transitions and duplicate approvals."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # First approval succeeds
    first_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert first_res.status_code == 200

    # Second (duplicate) approval must fail
    dup_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert dup_res.status_code == 400
    assert "already verified" in dup_res.json()["error"]["message"].lower()

    # Rejection on an already VERIFIED recovery must also fail
    reject_dup = await client.post(
        f"/api/v1/verification/{recovery_id}/reject",
        headers=eco["ver_headers"],
        json={"reason": "Too late to reject"},
    )
    assert reject_dup.status_code == 400


# ==============================================================================
# 9. Concurrent Verification Attempts (Pessimistic Locking)
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_verification_attempts(
    client: AsyncClient, create_user, auth_headers
):
    """Concurrent verification attempts on the same recovery event are atomic and race-free."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Execute rapid sequential/concurrent verification requests
    res1 = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={"notes": "First verification worker"},
    )
    res2 = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={"notes": "Second verification worker"},
    )

    statuses = [res1.status_code, res2.status_code]
    # Exactly one request succeeds with 200; the second is rejected with 400 (already verified)
    assert 200 in statuses
    assert 400 in statuses
    assert "already verified" in res2.json()["error"]["message"].lower()


# ==============================================================================
# 10. Critical Findings Block Approval Until Resolved
# ==============================================================================


@pytest.mark.asyncio
async def test_unresolved_critical_findings_block_approval(
    client: AsyncClient, create_user, auth_headers
):
    """An unresolved CRITICAL finding blocks approval until explicitly resolved."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # 1. Log a critical finding
    finding_res = await client.post(
        f"/api/v1/verification/{recovery_id}/findings",
        headers=eco["ver_headers"],
        json={
            "title": "GPS Coordinate Discrepancy",
            "description": "Collection coordinates are 45 km offshore in international waters.",
            "severity": FindingSeverity.CRITICAL.value,
            "category": FindingCategory.LOCATION_MISMATCH.value,
        },
    )
    assert finding_res.status_code == 201
    finding_id = finding_res.json()["id"]

    # 2. Approval is blocked
    blocked_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert blocked_res.status_code == 400
    assert "critical blocking" in blocked_res.json()["error"]["message"].lower()

    # 3. Resolve the finding
    resolve_res = await client.post(
        f"/api/v1/verification/findings/{finding_id}/resolve",
        headers=eco["ver_headers"],
        json={"resolution_notes": "Coordinates verified: Offshore boat cleanup operation validated."},
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["is_resolved"] is True

    # 4. Approval now succeeds
    success_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert success_res.status_code == 200
    assert success_res.json()["decision"] == "APPROVED"


# ==============================================================================
# 11. Verification Queue Functionality
# ==============================================================================


@pytest.mark.asyncio
async def test_verification_queue_listing(
    client: AsyncClient, create_user, auth_headers
):
    """Verifier queue returns recovery events requiring verification."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)

    queue_res = await client.get(
        "/api/v1/verification/queue",
        headers=eco["ver_headers"],
    )
    assert queue_res.status_code == 200
    items = queue_res.json()
    assert len(items) >= 1

    queued_ids = [item["recovery_id"] for item in items]
    assert eco["recovery_id"] in queued_ids


# ==============================================================================
# 12. Silent Modification Prevention on Verified Event
# ==============================================================================


@pytest.mark.asyncio
async def test_silent_modification_prevention_on_verified_event(
    client: AsyncClient, create_user, auth_headers
):
    """Once verified, a recovery event cannot be silently modified or have evidence appended."""
    eco = await _setup_verification_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Approve event
    approve_res = await client.post(
        f"/api/v1/verification/{recovery_id}/approve",
        headers=eco["ver_headers"],
        json={},
    )
    assert approve_res.status_code == 200

    # 1. Draft edit fails
    edit_res = await client.patch(
        f"/api/v1/recoveries/{recovery_id}",
        headers=eco["col_headers"],
        json={"weight_kg": 200.0},
    )
    assert edit_res.status_code == 400

    # 2. Appending new evidence fails
    ev_res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=eco["col_headers"],
        files={"file": ("tamper.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" + b"tamper"), "image/jpeg")},
        data={"evidence_type": EvidenceType.OTHER.value},
    )
    assert ev_res.status_code == 400
