"""Redis connection pool and FastAPI dependency.

Reuses the existing ``REDIS_URL`` from Settings (same instance Celery uses).
All connections are synchronous — matches the rest of the API layer.
"""

from __future__ import annotations

import threading

import redis

from app.core.config import settings

# ---------------------------------------------------------------------------
# Connection pool — module-level singleton, opened lazily
# ---------------------------------------------------------------------------

_pool: redis.ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> redis.ConnectionPool:
    """Return the shared connection pool, creating it on first call.

    Thread-safe: only one thread creates the pool; all others wait and
    receive the same instance.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            # Double-checked locking — another thread may have created
            # the pool while we were waiting for the lock.
            if _pool is None:
                _pool = redis.ConnectionPool.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    max_connections=20,
                )
    return _pool


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_redis():
    """FastAPI dependency — yields a Redis connection per request.

    Usage::

        @router.post("/example")
        def example(r: redis.Redis = Depends(get_redis)):
            r.set("key", "value")
    """
    r = redis.Redis(connection_pool=_get_pool())
    try:
        yield r
    finally:
        r.close()


# ---------------------------------------------------------------------------
# Standalone access (for code that runs outside a request cycle)
# ---------------------------------------------------------------------------


def get_redis_client() -> redis.Redis:
    """Return a Redis client using the shared pool.

    Use this outside of FastAPI request handling (e.g. in Celery tasks
    or startup scripts) where ``Depends()`` is not available.
    """
    return redis.Redis(connection_pool=_get_pool())


def get_redis_sync() -> redis.Redis | None:
    """Get a Redis client, returning None if unreachable (no exception).

    Safe to call from Celery workers or startup code where Redis may
    not be available.  Graceful degradation — callers check for None.
    """
    try:
        return get_redis_client()
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("Redis unavailable — returning None.")
        return None
