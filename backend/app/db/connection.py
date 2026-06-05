"""asyncpg connection pool factory.

Provides create_pool / close_pool for the NovelScript backend.
Uses asyncpg directly for raw SQL operations (init.sql, migrations) while
SQLModel / SQLAlchemy async sessions handle everyday CRUD.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def create_pool(dsn: str, **kwargs) -> asyncpg.Pool:
    """Create (or recreate) the global asyncpg connection pool.

    Args:
        dsn: PostgreSQL connection string (asyncpg format).
        **kwargs: Forwarded to asyncpg.create_pool
                  (min_size, max_size, command_timeout, …).

    Returns:
        The newly created pool instance.
    """
    global _pool

    # Close any existing pool before replacing
    if _pool is not None:
        await close_pool()

    logger.info("Creating asyncpg connection pool …")
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=kwargs.pop("min_size", 2),
        max_size=kwargs.pop("max_size", 10),
        **kwargs,
    )
    logger.info("asyncpg pool created (min=%d, max=%d).", 2, 10)
    return _pool


async def close_pool() -> None:
    """Gracefully close the global asyncpg pool."""
    global _pool
    if _pool is not None:
        logger.info("Closing asyncpg connection pool …")
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed.")


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return the current pool instance (may be None before init)."""
    return _pool
