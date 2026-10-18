"""PLASTIFY Pytest Configuration and Test Fixtures.

Configures an isolated in-memory SQLite database, mocked Redis client,
and HTTPX AsyncClient for hermetic automated testing without external dependencies.
"""

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.redis import get_redis_client
from app.main import create_application
from app.models.base import Base


# Configure test settings override
def get_test_settings() -> Settings:
    return Settings(
        ENVIRONMENT="test",
        DEBUG=True,
        ASYNC_DATABASE_URL="sqlite+aiosqlite:///:memory:",
        DATABASE_URL="sqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        LOG_LEVEL="WARNING",
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for pytest-asyncio."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a fresh in-memory SQLite async engine for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated async database session."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_redis():
    """Create an AsyncMock representing the Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping.return_value = True
    redis_mock.get.return_value = None
    redis_mock.set.return_value = True
    return redis_mock


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX AsyncClient configured with test dependency overrides."""
    from app.api.v1.endpoints.health import get_health_service
    from app.services.health import HealthService

    app = create_application()

    # Override database dependency with the test in-memory session
    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_get_redis_client():
        yield mock_redis

    async def mock_db_check():
        return True, 1.0, None

    async def mock_redis_check():
        return True, 0.5, None

    def override_get_health_service():
        return HealthService(
            settings=get_test_settings(),
            db_check=mock_db_check,
            redis_check=mock_redis_check,
        )

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_redis_client] = override_get_redis_client
    app.dependency_overrides[get_settings] = get_test_settings
    app.dependency_overrides[get_health_service] = override_get_health_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def create_user(db_session: AsyncSession):
    """Fixture returning a factory function to create persistent test users."""
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async def _create(
        email: str = "test@plastify.io",
        password: str = "SecurePass123!",
        role: UserRole = UserRole.CORPORATE,
        organization_id=None,
        is_active: bool = True,
        first_name: str = "Test",
        last_name: str = "User",
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=role,
            organization_id=organization_id,
            is_active=is_active,
            is_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        return user

    return _create


@pytest.fixture
def auth_headers():
    """Fixture returning a helper function to create Authorization Bearer headers for a user."""
    from app.core.security import create_access_token

    def _headers(user) -> dict:
        token = create_access_token(
            subject=user.id,
            claims={
                "email": user.email,
                "role": user.role.value,
                "org_id": str(user.organization_id) if user.organization_id else None,
            },
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers
