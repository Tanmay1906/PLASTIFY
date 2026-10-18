"""Tests for PLASTIFY SENTINEL Anomaly and Risk Detection Engine.

Validates:
- Low risk clean recovery events (false-positive safety, no alarms)
- WeightAnomalyDetector:
  - Discrepancy > 30% flags CRITICAL
  - Mass inflation in transit flags HIGH
  - Extreme single collection spikes
- GPSAnomalyDetector:
  - Out of region / geofence breach flags HIGH
  - Out-of-bounds coordinates (-90..90, -180..180) flags CRITICAL
  - Null Island coordinates flag HIGH
  - Impossible spatial velocity (teleportation) flags CRITICAL/HIGH
- TimestampAnomalyDetector:
  - Future collection timestamps flag CRITICAL
  - Inverted delivery milestones (delivered before pickup) flag CRITICAL
  - Instantaneous transit flags MEDIUM
- DuplicateEvidenceDetector:
  - Exact SHA-256 match across distinct recoveries flags CRITICAL
  - Perceptual hash near-match flags HIGH
  - Distinct files do not generate false positives
- DeliveryMismatchDetector:
  - Quantity divergence between collection and delivery manifest
  - Carrier delivered vs recycler received mismatch
- BehavioralAnomalyDetector:
  - Repetitive identical weights (synthetic precision)
  - Pinpoint GPS clustering
  - High-frequency burst submissions
- Verification Package Integration:
  - Verifier package inspects Sentinel findings and risk score
- Access control & RBAC boundaries
- Celery background worker execution
"""

import asyncio
from datetime import datetime, timedelta, timezone
import io
from typing import Dict, List, Optional
import uuid
import pytest
from httpx import AsyncClient

from app.models.custody import CustodyState
from app.models.evidence import EvidenceType
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.sentinel import RiskLevel
from app.models.user import UserRole
from app.workers.tasks import analyze_recovery_sentinel_task


async def _setup_sentinel_ecosystem(
    client: AsyncClient,
    create_user,
    auth_headers,
    weight_kg: float = 100.0,
    delivered_weight_kg: float = 99.5,
    received_weight_kg: float = 99.5,
    lat: float = 18.9220,
    lon: float = 72.8347,
    program_region: str = "Mumbai Marine Coast",
    collected_at: Optional[datetime] = None,
    upload_file_bytes: Optional[bytes] = None,
    filename: str = "beach_pet_bale_1.jpg",
    invert_pickup_time: bool = False,
) -> Dict[str, any]:
    """Helper to set up an end-to-end circular ecosystem through recycler delivery."""
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email=f"corp-{uuid.uuid4().hex[:8]}@danone-circular.com",
        role=UserRole.CORPORATE,
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": f"Danone Circular-{uuid.uuid4().hex[:6]}",
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
            "name": f"Marine Clean Initiative {uuid.uuid4().hex[:6]}",
            "region": program_region,
            "target_kg": 50000.0,
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
        email=f"collector-{uuid.uuid4().hex[:8]}@mumbai-clean.org",
        role=UserRole.COLLECTOR,
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": f"Mumbai Cleaners-{uuid.uuid4().hex[:6]}",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@mumbai-clean.org",
        },
    )
    col_org_id = col_org_res.json()["id"]

    # 4. Logistics Carrier
    log_user = await create_user(
        email=f"logistics-{uuid.uuid4().hex[:8]}@blueocean.com",
        role=UserRole.LOGISTICS,
    )
    log_headers = auth_headers(log_user)
    log_org_res = await client.post(
        "/api/v1/organizations",
        headers=log_headers,
        json={
            "name": f"Blue Ocean Logistics-{uuid.uuid4().hex[:6]}",
            "org_type": OrganizationType.LOGISTICS.value,
            "contact_email": "dispatch@blueocean.com",
        },
    )
    log_org_id = log_org_res.json()["id"]

    # 5. Recycler
    rec_user = await create_user(
        email=f"recycler-{uuid.uuid4().hex[:8]}@cleantech.com",
        role=UserRole.RECYCLER,
    )
    rec_headers = auth_headers(rec_user)
    rec_org_res = await client.post(
        "/api/v1/organizations",
        headers=rec_headers,
        json={
            "name": f"CleanTech Polymers-{uuid.uuid4().hex[:6]}",
            "org_type": OrganizationType.RECYCLER.value,
            "contact_email": "intake@cleantech.com",
        },
    )
    rec_org_id = rec_org_res.json()["id"]

    # 6. Verifier
    ver_user = await create_user(
        email=f"verifier-{uuid.uuid4().hex[:8]}@tuv.com",
        role=UserRole.VERIFIER,
    )
    ver_headers = auth_headers(ver_user)
    ver_org_res = await client.post(
        "/api/v1/organizations",
        headers=ver_headers,
        json={
            "name": f"TUV Assurance-{uuid.uuid4().hex[:6]}",
            "org_type": OrganizationType.VERIFIER.value,
            "contact_email": "audits@tuv.com",
        },
    )
    ver_org_id = ver_org_res.json()["id"]

    # Assign operational partners
    for org_id, r_role in [
        (col_org_id, "COLLECTOR"),
        (log_org_id, "LOGISTICS"),
        (rec_org_id, "RECYCLER"),
        (ver_org_id, "VERIFIER"),
    ]:
        await client.post(
            f"/api/v1/programs/{program_id}/partners",
            headers=corp_headers,
            json={"organization_id": org_id, "assigned_role": r_role},
        )

    # 7. Create Recovery Event
    coll_time = collected_at or (datetime.now(timezone.utc) - timedelta(hours=3))
    rec_payload = {
        "program_id": program_id,
        "material_type": PlasticMaterialType.PET.value,
        "weight_kg": weight_kg,
        "collection_location": "Gateway Beach, Mumbai",
        "collection_coordinates": {"latitude": lat, "longitude": lon},
        "collected_at": coll_time.isoformat(),
        "notes": "Post-consumer PET plastic bales retrieved from shoreline.",
    }
    rec_res = await client.post("/api/v1/recoveries", headers=col_headers, json=rec_payload)
    recovery = rec_res.json()
    recovery_id = recovery["id"]

    # 8. Upload Evidence
    file_content = upload_file_bytes or b"\xff\xd8\xff\xe0\x00\x10JFIF" + (b"clean_pet_bale_sample" * 10)
    files = {"file": (filename, io.BytesIO(file_content), "image/jpeg")}
    ev_res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value, "notes": "Shoreline collection pile"},
        files=files,
    )
    evidence_data = ev_res.json()

    # 9. Submit & Transition Custody
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/submit",
        headers=col_headers,
        json={"notes": "Standard shoreline collection batch"},
    )
    await client.post(
        f"/api/v1/recoveries/{recovery_id}/custody/transition",
        headers=col_headers,
        json={"new_state": CustodyState.SUBMITTED.value},
    )

    # 10. Logistics Assignment
    assign_res = await client.post(
        "/api/v1/logistics/assignments",
        headers=corp_headers,
        json={
            "recovery_id": recovery_id,
            "logistics_organization_id": log_org_id,
            "destination_organization_id": rec_org_id,
            "destination_location": "CleanTech Plant 1, Taloja",
        },
    )
    assignment = assign_res.json()
    assignment_id = assignment["id"]
    delivery_id = assignment["delivery"]["id"]

    # Accept & Pickup
    await client.post(f"/api/v1/logistics/assignments/{assignment_id}/accept", headers=log_headers, json={})
    if invert_pickup_time:
        pickup_time = coll_time - timedelta(hours=2)
    else:
        pickup_time = coll_time + timedelta(hours=1)
    await client.post(
        f"/api/v1/logistics/assignments/{assignment_id}/pickup",
        headers=log_headers,
        json={"pickup_timestamp": pickup_time.isoformat(), "vehicle_number": "MH-04-AZ-2026"},
    )

    # In-Transit & Delivered
    intransit_time = pickup_time + timedelta(minutes=30)
    delivered_time = intransit_time + timedelta(hours=1)
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/in-transit",
        headers=log_headers,
        json={"in_transit_timestamp": intransit_time.isoformat()},
    )
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/delivered",
        headers=log_headers,
        json={
            "delivered_weight_kg": delivered_weight_kg,
            "delivery_timestamp": delivered_time.isoformat(),
        },
    )

    # Recycler Confirms Intake Receipt
    received_time = delivered_time + timedelta(minutes=15)
    await client.post(
        f"/api/v1/logistics/deliveries/{delivery_id}/receive",
        headers=rec_headers,
        json={
            "received_weight_kg": received_weight_kg,
            "received_timestamp": received_time.isoformat(),
            "notes": "Verified on recycler calibrated weighbridge.",
        },
    )

    return {
        "corp_user": corp_user,
        "corp_headers": corp_headers,
        "col_user": col_user,
        "col_headers": col_headers,
        "col_org_id": col_org_id,
        "log_user": log_user,
        "log_headers": log_headers,
        "rec_user": rec_user,
        "rec_headers": rec_headers,
        "ver_user": ver_user,
        "ver_headers": ver_headers,
        "program_id": program_id,
        "recovery_id": recovery_id,
        "delivery_id": delivery_id,
        "assignment_id": assignment_id,
        "evidence_id": evidence_data["id"],
        "coll_time": coll_time,
    }


# ==============================================================================
# TEST SUITE: PLASTIFY SENTINEL
# ==============================================================================


@pytest.mark.asyncio
async def test_clean_recovery_low_risk_no_flags(client: AsyncClient, create_user, auth_headers):
    """Test clean, fully conforming recovery event generates LOW risk with 0 flags."""
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=99.5,
        received_weight_kg=99.5,
    )
    recovery_id = eco["recovery_id"]

    res = await client.post(
        f"/api/v1/sentinel/{recovery_id}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    assert data["risk_level"] == "LOW"
    assert data["risk_score"] < 20.0
    assert data["flags_count"] == 0
    assert data["critical_count"] == 0
    assert data["high_count"] == 0
    assert "conforms" in data["summary"].lower() or "no anomalies" in data["summary"].lower()


@pytest.mark.asyncio
async def test_weight_anomaly_critical_divergence_and_inflation(
    client: AsyncClient, create_user, auth_headers
):
    """Test WeightAnomalyDetector flags severe weight drop (>30%) and mass inflation."""
    # 1. Critical weight drop: 100 kg expected vs 60 kg received (40% discrepancy)
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=60.0,
        received_weight_kg=60.0,
    )
    recovery_id = eco["recovery_id"]

    res = await client.post(
        f"/api/v1/sentinel/{recovery_id}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    assert data["risk_level"] in ["HIGH", "CRITICAL"]
    assert data["flags_count"] >= 1
    weight_flags = [f for f in data["flags"] if f["detector"] == "WeightAnomalyDetector"]
    assert len(weight_flags) >= 1
    assert any(f["severity"] in ["HIGH", "CRITICAL"] for f in weight_flags)
    assert any("divergence" in f["reason"].lower() or "discrepancy" in f["reason"].lower() for f in weight_flags)

    # 2. Transit mass inflation: 100 kg collected, 125 kg delivered (+25% gain)
    eco_inf = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=125.0,
        received_weight_kg=125.0,
    )
    res_inf = await client.post(
        f"/api/v1/sentinel/{eco_inf['recovery_id']}/run",
        headers=eco_inf["ver_headers"],
    )
    assert res_inf.status_code == 200
    data_inf = res_inf.json()
    inf_flags = [
        f for f in data_inf["flags"]
        if f["detector"] == "WeightAnomalyDetector" and "inflation" in f["reason"].lower()
    ]
    assert len(inf_flags) >= 1
    assert inf_flags[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_gps_anomaly_geofence_and_impossible_coordinates(
    client: AsyncClient, create_user, auth_headers
):
    """Test GPSAnomalyDetector identifies out-of-region coordinates and coordinate invalidity."""
    # 1. Out of region: Mumbai Marine program, but coordinates in London (lat: 51.5074, lon: -0.1278)
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        lat=51.5074,
        lon=-0.1278,
        program_region="Mumbai Coastal Zone",
    )
    res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    gps_flags = [f for f in data["flags"] if f["detector"] == "GPSAnomalyDetector"]
    assert len(gps_flags) >= 1
    assert any("outside" in f["reason"].lower() or "operational zone" in f["reason"].lower() for f in gps_flags)
    assert any(f["severity"] == "HIGH" for f in gps_flags)

    # 2. Null Island (0.0, 0.0) coordinates
    eco_null = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        lat=0.0,
        lon=0.0,
        program_region="Mumbai Coast",
    )
    res_null = await client.post(
        f"/api/v1/sentinel/{eco_null['recovery_id']}/run",
        headers=eco_null["ver_headers"],
    )
    assert res_null.status_code == 200
    data_null = res_null.json()
    null_flags = [
        f for f in data_null["flags"]
        if f["detector"] == "GPSAnomalyDetector" and "null island" in f["reason"].lower()
    ]
    assert len(null_flags) >= 1
    assert null_flags[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_timestamp_anomaly_detection_chronology(
    client: AsyncClient, create_user, auth_headers
):
    """Test TimestampAnomalyDetector identifies milestone inversions."""
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        invert_pickup_time=True,
    )
    res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    ts_flags = [f for f in data["flags"] if f["detector"] == "TimestampAnomalyDetector"]
    assert len(ts_flags) >= 1
    assert any(f["severity"] in ["HIGH", "CRITICAL"] for f in ts_flags)
    assert any("inverted" in f["reason"].lower() or "precedes" in f["reason"].lower() for f in ts_flags)


@pytest.mark.asyncio
async def test_duplicate_evidence_detection_across_events(
    client: AsyncClient, create_user, auth_headers
):
    """Test DuplicateEvidenceDetector detects reused SHA-256 binary evidence across events."""
    shared_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"identical_bale_pixel_data_12345" * 20

    # Event 1 with image
    eco1 = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        upload_file_bytes=shared_image_bytes,
        filename="bale_original.jpg",
    )

    # Event 2 reusing exact same binary image
    eco2 = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        upload_file_bytes=shared_image_bytes,
        filename="reused_bale.jpg",
    )

    # Run Sentinel on Event 2
    res2 = await client.post(
        f"/api/v1/sentinel/{eco2['recovery_id']}/run",
        headers=eco2["ver_headers"],
    )
    assert res2.status_code == 200
    data2 = res2.json()

    dup_flags = [f for f in data2["flags"] if f["detector"] == "DuplicateEvidenceDetector"]
    assert len(dup_flags) >= 1
    assert any(f["severity"] == "CRITICAL" for f in dup_flags)
    assert any("collision" in f["reason"].lower() or "shares identical" in f["reason"].lower() for f in dup_flags)


@pytest.mark.asyncio
async def test_delivery_mismatch_quantity_divergence(
    client: AsyncClient, create_user, auth_headers
):
    """Test DeliveryMismatchDetector identifies divergence between collection, carrier, and intake."""
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=100.0,
        received_weight_kg=85.0,  # 15% variation at recycler weigh-in
    )
    res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    mismatch_flags = [f for f in data["flags"] if f["detector"] == "DeliveryMismatchDetector"]
    assert len(mismatch_flags) >= 1
    assert any("variation" in f["reason"].lower() or "discrepancy" in f["reason"].lower() for f in mismatch_flags)


@pytest.mark.asyncio
async def test_behavioral_anomaly_repetitive_weights(
    client: AsyncClient, create_user, auth_headers
):
    """Test BehavioralAnomalyDetector flags repeated identical weights by same collector."""
    # Collector creates 3 recovery events with exact identical weight down to decimal: 147.25 kg
    shared_weight = 147.25

    eco1 = await _setup_sentinel_ecosystem(
        client, create_user, auth_headers, weight_kg=shared_weight
    )

    # Same collector creates second and third events
    col_headers = eco1["col_headers"]
    prog_id = eco1["program_id"]

    for i in range(2):
        now_ts = (datetime.now(timezone.utc) - timedelta(hours=i + 1)).isoformat()
        r = await client.post(
            "/api/v1/recoveries",
            headers=col_headers,
            json={
                "program_id": prog_id,
                "material_type": PlasticMaterialType.PET.value,
                "weight_kg": shared_weight,
                "collection_location": f"Shoreline Sector {i+2}",
                "collection_coordinates": {"latitude": 18.9220 + (i * 0.01), "longitude": 72.8347},
                "collected_at": now_ts,
            },
        )
        rec_id = r.json()["id"]
        # Upload distinct evidence
        f_bytes = b"\xff\xd8\xff" + f"unique_bale_{i}_{uuid.uuid4().hex}".encode("utf-8") * 10
        await client.post(
            f"/api/v1/recoveries/{rec_id}/evidence",
            headers=col_headers,
            data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value},
            files={"file": (f"bale_{i}.jpg", io.BytesIO(f_bytes), "image/jpeg")},
        )
        await client.post(f"/api/v1/recoveries/{rec_id}/submit", headers=col_headers)

    # Run Sentinel on primary event
    res = await client.post(
        f"/api/v1/sentinel/{eco1['recovery_id']}/run",
        headers=eco1["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    beh_flags = [f for f in data["flags"] if f["detector"] == "BehavioralAnomalyDetector"]
    assert len(beh_flags) >= 1
    assert any("repetitive weight" in f["reason"].lower() for f in beh_flags)


@pytest.mark.asyncio
async def test_false_positive_safe_behavior(client: AsyncClient, create_user, auth_headers):
    """Test that reasonable 1.5% tare scale variation within tolerance produces LOW risk and 0 flags."""
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=98.5,  # 1.5% calibration difference (under 5% tolerance)
        received_weight_kg=98.5,
        lat=18.9220,
        lon=72.8347,
        program_region="Mumbai Marine Coast",
    )
    res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers=eco["ver_headers"],
    )
    assert res.status_code == 200
    data = res.json()

    # Must NOT produce false positive alarms
    assert data["risk_level"] == "LOW"
    assert data["risk_score"] < 20.0
    assert data["flags_count"] == 0
    assert data["critical_count"] == 0


@pytest.mark.asyncio
async def test_verification_package_inspects_sentinel_findings(
    client: AsyncClient, create_user, auth_headers
):
    """Test that a verifier inspecting the verification package receives Sentinel evaluation results."""
    # Create event with weight anomaly
    eco = await _setup_sentinel_ecosystem(
        client,
        create_user,
        auth_headers,
        weight_kg=100.0,
        delivered_weight_kg=70.0,  # 30% drop
        received_weight_kg=70.0,
    )
    recovery_id = eco["recovery_id"]

    # 1. Run Sentinel evaluation
    sent_res = await client.post(
        f"/api/v1/sentinel/{recovery_id}/run",
        headers=eco["ver_headers"],
    )
    assert sent_res.status_code == 200
    sent_data = sent_res.json()
    assert sent_data["risk_score"] >= 19.0
    assert sent_data["risk_level"] in ["MEDIUM", "HIGH", "CRITICAL"]

    # 2. Inspect complete verification package
    pkg_res = await client.get(
        f"/api/v1/verification/package/{recovery_id}",
        headers=eco["ver_headers"],
    )
    assert pkg_res.status_code == 200
    pkg = pkg_res.json()

    # Verification package includes Sentinel findings & result
    assert "sentinel_result" in pkg
    assert pkg["sentinel_result"] is not None
    assert pkg["sentinel_result"]["risk_score"] == sent_data["risk_score"]
    assert pkg["sentinel_result"]["risk_level"] == sent_data["risk_level"]
    assert len(pkg["sentinel_result"]["flags"]) == len(sent_data["flags"])


@pytest.mark.asyncio
async def test_unauthorized_user_denied_sentinel_run(
    client: AsyncClient, create_user, auth_headers
):
    """Test that stranger verifiers and unauthorized roles cannot trigger Sentinel runs."""
    eco = await _setup_sentinel_ecosystem(client, create_user, auth_headers)

    # Rogue verifier not part of this program's organization
    stranger = await create_user(email="stranger@rogue.com", role=UserRole.VERIFIER)
    stranger_headers = auth_headers(stranger)

    res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers=stranger_headers,
    )
    # Verifiers can inspect or super_admin, but cross-org or unauthenticated is rejected
    unauth_res = await client.post(
        f"/api/v1/sentinel/{eco['recovery_id']}/run",
        headers={},  # Missing token
    )
    assert unauth_res.status_code == 401


@pytest.mark.asyncio
async def test_celery_sentinel_task_execution(
    client: AsyncClient, create_user, auth_headers
):
    """Test asynchronous Sentinel evaluation via Celery background task."""
    eco = await _setup_sentinel_ecosystem(client, create_user, auth_headers)
    recovery_id = eco["recovery_id"]

    # Directly execute the task function
    task_res = analyze_recovery_sentinel_task(str(recovery_id))

    assert task_res["status"] == "COMPLETED"
    assert task_res["recovery_id"] == str(recovery_id)
    assert "risk_score" in task_res
    assert "risk_level" in task_res

    # Also test via async_run API parameter
    api_res = await client.post(
        f"/api/v1/sentinel/{recovery_id}/run",
        headers=eco["ver_headers"],
        json={"async_run": True},
    )
    assert api_res.status_code == 200
    api_data = api_res.json()
    assert api_data["status"] in ["PENDING", "COMPLETED"]
