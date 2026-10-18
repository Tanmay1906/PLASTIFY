"""Tests for Database Models and Repository Layer."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SystemAuditLog
from app.repositories.audit import AuditRepository


@pytest.mark.asyncio
async def test_audit_repository_crud(db_session: AsyncSession):
    """Test creating, fetching, and counting records using AuditRepository."""
    repo = AuditRepository(session=db_session)

    # 1. Initial count
    count_before = await repo.count()
    assert count_before == 0

    # 2. Create audit log
    log = await repo.create_log(
        event_type="SYSTEM_BOOT",
        component="core.engine",
        message="Backend foundation initialized",
        request_id="req-boot-001",
        details={"version": "0.1.0"},
    )
    assert log.id is not None
    assert log.event_type == "SYSTEM_BOOT"
    assert log.component == "core.engine"
    assert log.details == {"version": "0.1.0"}

    # 3. Retrieve by ID
    fetched = await repo.get_by_id(log.id)
    assert fetched is not None
    assert fetched.id == log.id
    assert fetched.message == "Backend foundation initialized"

    # 4. List and count
    all_logs = await repo.list(skip=0, limit=10)
    assert len(all_logs) == 1
    assert await repo.count() == 1

    # 5. Filter by event_type
    filtered = await repo.get_by_event_type("SYSTEM_BOOT")
    assert len(filtered) == 1
    assert filtered[0].id == log.id

    unmatched = await repo.get_by_event_type("UNKNOWN_EVENT")
    assert len(unmatched) == 0
