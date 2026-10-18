"""Tests for Request Correlation ID Middleware and Headers."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_id_generated_automatically(client: AsyncClient):
    """When client provides no X-Request-ID, the middleware generates a new UUID."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 10
    assert "X-Process-Time" in response.headers


@pytest.mark.asyncio
async def test_request_id_propagated_from_caller(client: AsyncClient):
    """When client supplies X-Request-ID, the middleware preserves and echoes it back."""
    custom_id = "test-correlation-id-998877"
    response = await client.get("/api/v1/health/live", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id
