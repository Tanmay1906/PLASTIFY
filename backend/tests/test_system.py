"""Tests for System Diagnostic endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_system_info(client: AsyncClient):
    """GET /api/v1/system/info returns valid platform metadata."""
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["app_name"] == "PLASTIFY"
    assert "version" in data
    assert "python_version" in data
    assert data["api_prefix"] == "/api/v1"


@pytest.mark.asyncio
async def test_system_ping(client: AsyncClient):
    """GET /api/v1/system/ping returns pong message and correlation ID."""
    response = await client.get("/api/v1/system/ping", headers={"X-Request-ID": "test-ping-req-123"})
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "pong"
    assert data["request_id"] == "test-ping-req-123"
    assert "timestamp" in data
