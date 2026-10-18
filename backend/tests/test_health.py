"""Tests for Health and Readiness probes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_probe(client: AsyncClient):
    """Liveness probe must return 200 and status 'live'."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "live"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_readiness_probe_healthy(client: AsyncClient):
    """Readiness probe returns 200 and component breakdown when services respond."""
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "components" in data
    assert data["components"]["postgres"]["status"] == "healthy"
    assert data["components"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_readiness_probe_unhealthy(client: AsyncClient):
    """Readiness probe returns 503 when a critical backing service is down."""
    from app.api.v1.endpoints.health import get_health_service
    from app.services.health import HealthService
    from app.core.config import get_settings

    # Reconfigure app dependency override to simulate DB failure
    app = client._transport.app  # ASGI app instance

    async def mock_failed_db_check():
        return False, 5.0, "Connection refused"

    async def mock_redis_check():
        return True, 1.0, None

    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=get_settings(),
        db_check=mock_failed_db_check,
        redis_check=mock_redis_check,
    )

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["components"]["postgres"]["status"] == "unhealthy"
    assert data["components"]["postgres"]["error"] == "Connection refused"


@pytest.mark.asyncio
async def test_health_overview(client: AsyncClient):
    """Comprehensive health check returns service, version, uptime, and components."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "PLASTIFY"
    assert "version" in data
    assert "uptime_seconds" in data
    assert "components" in data


@pytest.mark.asyncio
async def test_root_discovery(client: AsyncClient):
    """Root discovery endpoint returns metadata and documentation routes."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "docs" in data
    assert "version" in data
    assert data["docs"] == "/docs"


@pytest.mark.asyncio
async def test_root_health_alias(client: AsyncClient):
    """Root /health alias returns live indicator."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "live"
