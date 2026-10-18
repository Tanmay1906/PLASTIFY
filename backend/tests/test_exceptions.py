"""Tests for Global Exception Handlers and Error Envelopes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_not_found_error_envelope(client: AsyncClient):
    """Accessing non-existent endpoints yields standardized 404 error envelope."""
    response = await client.get("/api/v1/non-existent-resource")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["code"] == "HTTP_404"
    assert "timestamp" in data
    assert "request_id" in data
    assert response.headers.get("X-Request-ID") == data["request_id"]
