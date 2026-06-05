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
    # SQLAlchemy DSNs use postgresql+asyncpg:// — strip the +asyncpg driver
    # prefix so asyncpg gets a plain postgresql:// URL.
    asyncpg_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    _pool = await asyncpg.create_pool(
        asyncpg_dsn,
        min_size=kwargs.pop("min_size", 2),
        max_size=kwargs.pop("max_size", 10),
        **kwargs,
    )
    logger.info("asyncpg pool created (min=%d, max=%d).", 2, 10)
    return _pool


async def close_pool() -> None:
    """Gracefully close the global asyncpg pool.

    Catches exceptions from pools whose event loop has already been
    torn down (happens on Windows when tests switch event loops between
    modules).
    """
    global _pool
    if _pool is not None:
        logger.info("Closing asyncpg connection pool …")
        try:
            await _pool.close()
        except Exception:
            logger.debug("Pool close raised (likely stale event loop) — discarding.")
        finally:
            _pool = None
        logger.info("asyncpg pool closed.")


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return the current pool instance (may be None before init)."""
    return _pool
