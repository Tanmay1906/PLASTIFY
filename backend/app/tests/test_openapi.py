"""Tests for OpenAPI Specification and Swagger Docs."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_openapi_json(client: AsyncClient):
    """Verify OpenAPI 3.x schema generation and metadata."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert schema["info"]["title"] == "PLASTIFY"
    assert "/api/v1/health/live" in schema["paths"]
    assert "/api/v1/health/ready" in schema["paths"]
    assert "/api/v1/system/info" in schema["paths"]


@pytest.mark.asyncio
async def test_swagger_ui_html(client: AsyncClient):
    """Verify Swagger UI docs endpoint loads successfully."""
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
