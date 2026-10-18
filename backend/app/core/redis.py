"""PLASTIFY Async Redis Infrastructure.

Configures connection pooling and async Redis client lifecycle.
"""

import logging
import time
from typing import AsyncGenerator, Optional, Tuple
from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings

logger = logging.getLogger("plastify.redis")

_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None


def get_redis_pool() -> ConnectionPool:
    """Retrieve or initialize the Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = ConnectionPool.from_url(
            settings.redis_url_constructed,
            decode_responses=True,
            max_connections=50,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        logger.info("Redis connection pool initialized")
    return _redis_pool


def get_redis() -> Redis:
    """Retrieve or initialize the singleton Redis client instance."""
    global _redis_client
    if _redis_client is None:
        pool = get_redis_pool()
        _redis_client = Redis(connection_pool=pool)
    return _redis_client


async def close_redis() -> None:
    """Gracefully close Redis client and connection pool."""
    global _redis_client, _redis_pool
    if _redis_client is not None:
        logger.info("Closing Redis client")
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool is not None:
        logger.info("Disconnecting Redis connection pool")
        await _redis_pool.disconnect()
        _redis_pool = None


async def get_redis_client() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency yielding an active Redis client."""
    client = get_redis()
    yield client


async def check_redis_connection() -> Tuple[bool, float, Optional[str]]:
    """Probe Redis with PING for health/readiness checks.

    Returns:
        (is_healthy, latency_ms, error_message)
    """
    start_time = time.perf_counter()
    try:
        client = get_redis()
        pong = await client.ping()
        latency_ms = (time.perf_counter() - start_time) * 1000
        if pong:
            return True, round(latency_ms, 2), None
        return False, round(latency_ms, 2), "PING returned non-truthy response"
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(f"Redis health check failed: {exc}")
        return False, round(latency_ms, 2), str(exc)
