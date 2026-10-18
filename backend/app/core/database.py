"""PLASTIFY Async Database Infrastructure.

Configures SQLAlchemy 2.x async engine, connection pool, session maker,
and dependency injection helpers.
"""

import logging
import time
from typing import AsyncGenerator, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger("plastify.database")

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Initialize or return the singleton SQLAlchemy AsyncEngine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        # If SQLite is used (e.g. for testing)
        if "sqlite" in settings.async_database_url_constructed:
            connect_args = {"check_same_thread": False}

        _engine = create_async_engine(
            settings.async_database_url_constructed,
            echo=settings.DB_ECHO,
            pool_size=settings.DB_POOL_SIZE if "sqlite" not in settings.async_database_url_constructed else None,
            max_overflow=settings.DB_MAX_OVERFLOW if "sqlite" not in settings.async_database_url_constructed else None,
            pool_timeout=settings.DB_POOL_TIMEOUT if "sqlite" not in settings.async_database_url_constructed else None,
            pool_recycle=settings.DB_POOL_RECYCLE if "sqlite" not in settings.async_database_url_constructed else None,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        logger.info(
            "SQLAlchemy async engine initialized",
            extra={"database_url_scheme": settings.async_database_url_constructed.split("://")[0]},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retrieve or create the session maker."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def close_db_engine() -> None:
    """Dispose of the database engine connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Disposing database engine connection pool")
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding transactional async database sessions."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_connection() -> Tuple[bool, float, Optional[str]]:
    """Probe the database connection for readiness checks.

    Returns:
        (is_healthy, latency_ms, error_message)
    """
    start_time = time.perf_counter()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - start_time) * 1000
        return True, round(latency_ms, 2), None
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(f"Database health check failed: {exc}")
        return False, round(latency_ms, 2), str(exc)
