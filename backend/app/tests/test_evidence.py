"""Tests for Evidence Management, Secure Object Storage, and Signed URLs.

Validates:
- 11-step evidence upload workflow
- Unauthorized upload denial (403)
- Dangerous file types and extensions rejection (400)
- Invalid MIME types rejection (400)
- Oversized and empty file rejection (400)
- Accurate cryptographic SHA-256 hash generation
- Evidence ownership and multi-tenant isolation
- Presigned signed URL generation and retrieval
- Malware scanner abstraction (EICAR signature rejection)
"""

import hashlib
import io
import pytest
from httpx import AsyncClient

from app.core.malware import EICAR_SIGNATURE
from app.models.evidence import EvidenceType
from app.models.organization import OrganizationType
from app.models.program import PlasticMaterialType, ProgramStatus
from app.models.user import UserRole


async def _setup_recovery_fixture(client: AsyncClient, create_user, auth_headers):
    """Setup a corporate program and an assigned collector who creates a recovery event."""
    # 1. Corporate Brand Owner
    corp_user = await create_user(
        email="sustainability@danone.com", role=UserRole.CORPORATE
    )
    corp_headers = auth_headers(corp_user)
    corp_org_res = await client.post(
        "/api/v1/organizations",
        headers=corp_headers,
        json={
            "name": "Danone Global Circular",
            "org_type": OrganizationType.CORPORATE.value,
            "contact_email": "sustainability@danone.com",
        },
    )
    corp_org_id = corp_org_res.json()["id"]

    # 2. Corporate Program
    prog_res = await client.post(
        "/api/v1/programs",
        headers=corp_headers,
        json={
            "name": "Delhi Coastal Clean 2026",
            "region": "DEL",
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
        email="collector@greendelhi.org", role=UserRole.COLLECTOR
    )
    col_headers = auth_headers(col_user)
    col_org_res = await client.post(
        "/api/v1/organizations",
        headers=col_headers,
        json={
            "name": "Green Delhi Waste Aggregators",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "ops@greendelhi.org",
        },
    )
    col_org_id = col_org_res.json()["id"]

    # 4. Assign Collector to Program
    await client.post(
        f"/api/v1/programs/{program_id}/partners",
        headers=corp_headers,
        json={
            "organization_id": col_org_id,
            "assigned_role": "COLLECTOR",
        },
    )

    # 5. Create Recovery Event
    rec_res = await client.post(
        "/api/v1/recoveries",
        headers=col_headers,
        json={
            "program_id": program_id,
            "material_type": PlasticMaterialType.PET.value,
            "weight_kg": 420.0,
            "collection_location": "Okhla Transfer Station, Delhi",
        },
    )
    assert rec_res.status_code == 201
    recovery = rec_res.json()

    return {
        "corp_user": corp_user,
        "corp_headers": corp_headers,
        "col_user": col_user,
        "col_headers": col_headers,
        "recovery_id": recovery["id"],
        "human_id": recovery["recovery_id"],
    }


@pytest.mark.asyncio
async def test_evidence_upload_workflow_and_hash_generation(
    client: AsyncClient, create_user, auth_headers
):
    """Test successful evidence upload, SHA-256 hash calculation, and signed URL generation."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    recovery_id = data["recovery_id"]

    sample_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    expected_hash = hashlib.sha256(sample_content).hexdigest()

    files = {"file": ("scale_receipt.png", io.BytesIO(sample_content), "image/png")}
    form_data = {
        "evidence_type": EvidenceType.WEIGHT_PHOTO.value,
        "notes": "Certified digital scale readout at weighbridge #4",
    }

    res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files=files,
        data=form_data,
    )
    assert res.status_code == 201
    evidence = res.json()

    assert evidence["recovery_id"] == recovery_id
    assert evidence["type"] == "WEIGHT_PHOTO"
    assert evidence["original_filename"] == "scale_receipt.png"
    assert evidence["mime_type"] == "image/png"
    assert evidence["size"] == len(sample_content)
    assert evidence["sha256_hash"] == expected_hash
    assert evidence["scan_status"] == "CLEAN"
    assert "storage_key" in evidence
    assert f"evidence/{recovery_id}/" in evidence["storage_key"]
    assert "download_url" in evidence
    assert evidence["download_url"].startswith("http")


@pytest.mark.asyncio
async def test_unauthorized_evidence_upload(
    client: AsyncClient, create_user, auth_headers
):
    """User from an unrelated organization cannot upload evidence to a private recovery event."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    recovery_id = data["recovery_id"]

    # Stranger collector from Org B
    stranger = await create_user(
        email="intruder@unrelated.org", role=UserRole.COLLECTOR
    )
    stranger_headers = auth_headers(stranger)
    await client.post(
        "/api/v1/organizations",
        headers=stranger_headers,
        json={
            "name": "Unrelated Waste Co",
            "org_type": OrganizationType.COLLECTOR.value,
            "contact_email": "intruder@unrelated.org",
        },
    )

    files = {"file": ("fake.jpg", io.BytesIO(b"fake image bytes"), "image/jpeg")}
    res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=stranger_headers,
        files=files,
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_reject_dangerous_and_invalid_files(
    client: AsyncClient, create_user, auth_headers
):
    """Server-side security rejects executable/script extensions and disallowed MIME types."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    recovery_id = data["recovery_id"]

    # 1. Dangerous executable extension (.exe)
    res_exe = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("exploit.exe", io.BytesIO(b"malicious payload"), "image/png")},
        data={"evidence_type": EvidenceType.OTHER.value},
    )
    assert res_exe.status_code == 400
    assert "prohibited" in res_exe.json()["error"]["message"]

    # 2. Dangerous script extension (.sh)
    res_sh = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("script.sh", io.BytesIO(b"#!/bin/bash\nrm -rf /"), "image/png")},
        data={"evidence_type": EvidenceType.OTHER.value},
    )
    assert res_sh.status_code == 400
    assert "prohibited" in res_sh.json()["error"]["message"]

    # 3. Disallowed MIME type (video/mp4)
    res_mime = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("video.png", io.BytesIO(b"dummy video"), "video/mp4")},
        data={"evidence_type": EvidenceType.OTHER.value},
    )
    assert res_mime.status_code == 400
    assert "MIME type" in res_mime.json()["error"]["message"]


@pytest.mark.asyncio
async def test_oversized_and_empty_file_rejection(
    client: AsyncClient, create_user, auth_headers
):
    """Empty files and files exceeding size limits are rejected."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    recovery_id = data["recovery_id"]

    # 1. Empty file (0 bytes)
    res_empty = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value},
    )
    assert res_empty.status_code == 400
    assert "empty" in res_empty.json()["error"]["message"]

    # 2. Oversized file (e.g. 16 MB with 15 MB limit)
    oversized_bytes = b"X" * (16 * 1024 * 1024)
    res_oversized = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files={"file": ("huge.jpg", io.BytesIO(oversized_bytes), "image/jpeg")},
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value},
    )
    assert res_oversized.status_code == 400
    assert "exceeds maximum allowable limit" in res_oversized.json()["error"]["message"]


@pytest.mark.asyncio
async def test_malware_scanner_rejection(
    client: AsyncClient, create_user, auth_headers
):
    """Malware scanner detects test virus signatures and halts ingestion."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    recovery_id = data["recovery_id"]

    files = {"file": ("document.pdf", io.BytesIO(EICAR_SIGNATURE), "application/pdf")}
    res = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files=files,
        data={"evidence_type": EvidenceType.RECEIPT.value},
    )
    assert res.status_code == 400
    assert "security verification failed" in res.json()["error"]["message"]


@pytest.mark.asyncio
async def test_signed_url_generation_and_evidence_listing(
    client: AsyncClient, create_user, auth_headers
):
    """Authorized users can list recovery evidence and fetch short-lived signed URLs."""
    data = await _setup_recovery_fixture(client, create_user, auth_headers)
    col_headers = data["col_headers"]
    recovery_id = data["recovery_id"]

    # Upload 2 evidence files
    f1 = {"file": ("site_photo.jpg", io.BytesIO(b"\xff\xd8\xff\xe0photo1"), "image/jpeg")}
    f2 = {"file": ("weigh_slip.pdf", io.BytesIO(b"%PDF-1.4\nslip"), "application/pdf")}

    r1 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files=f1,
        data={"evidence_type": EvidenceType.COLLECTION_PHOTO.value},
    )
    assert r1.status_code == 201
    evidence_1_id = r1.json()["id"]

    r2 = await client.post(
        f"/api/v1/recoveries/{recovery_id}/evidence",
        headers=col_headers,
        files=f2,
        data={"evidence_type": EvidenceType.RECEIPT.value},
    )
    assert r2.status_code == 201

    # 1. List evidence for recovery event
    list_res = await client.get(
        f"/api/v1/recoveries/{recovery_id}/evidence", headers=col_headers
    )
    assert list_res.status_code == 200
    evidence_list = list_res.json()
    assert len(evidence_list) == 2
    assert all("download_url" in item for item in evidence_list)

    # 2. Get single evidence record with signed URL
    get_res = await client.get(f"/api/v1/evidence/{evidence_1_id}", headers=col_headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == evidence_1_id
    assert "download_url" in get_res.json()

    # 3. Generate fresh signed URL with custom expiry
    url_res = await client.get(
        f"/api/v1/evidence/{evidence_1_id}/url?expires_in=600", headers=col_headers
    )
    assert url_res.status_code == 200
    url_data = url_res.json()
    assert url_data["evidence_id"] == evidence_1_id
    assert url_data["expires_in_seconds"] == 600
    assert "download_url" in url_data
    assert "X-Amz-Signature" in url_data["download_url"] or "mock_signature" in url_data["download_url"]

    # 4. Corporate owner can also view evidence
    corp_view = await client.get(
        f"/api/v1/recoveries/{recovery_id}/evidence", headers=data["corp_headers"]
    )
    assert corp_view.status_code == 200
    assert len(corp_view.json()) == 2
