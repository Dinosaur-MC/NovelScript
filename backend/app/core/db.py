"""Database lifecycle — session dependency and initialisation.

Provides the FastAPI ``get_db`` async generator and ``init_db`` which
creates all tables declared by SQLModel *and* executes ``init.sql``
via asyncpg for extensions, indexes, and any raw-DDL objects that
SQLModel cannot express (HNSW, GIN trigram, CHECK constraints on
non-enum columns, etc.).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Optional

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings
from app.db.connection import close_pool, create_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLAlchemy async engine (for SQLModel / ORM)
# ---------------------------------------------------------------------------
_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
)

_async_session_factory = sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an :class:`AsyncSession` per request; auto-close on teardown."""
    async with _async_session_factory() as session:  # type: ignore[attr-defined]
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Full database initialisation.

    1. Create the asyncpg connection pool (used by services for raw SQL).
    2. Execute ``init.sql`` via asyncpg to ensure extensions, indexes,
       CHECK constraints, and other PG-native objects exist.
    3. Create all SQLModel-managed tables (idempotent via
       ``create_all`` which uses ``IF NOT EXISTS`` internally with
       the asyncpg dialect).
    """
    logger.info("Initialising database …")

    # -- 1. asyncpg pool ------------------------------------------------ #
    await create_pool(settings.DATABASE_URL)

    # -- 2. Raw DDL (extensions, indexes, constraints) ------------------ #
    sql_path = Path(__file__).resolve().parent.parent / "db" / "init.sql"
    init_sql = sql_path.read_text(encoding="utf-8")

    pool = await _get_asyncpg_pool()
    if pool is None:
        raise RuntimeError("asyncpg pool was not created — check DATABASE_URL.")
    async with pool.acquire() as conn:
        await conn.execute(init_sql)

    logger.info("init.sql executed successfully.")

    # -- 3. SQLModel tables --------------------------------------------- #
    # IMPORTANT: import all sql.py models so SQLModel.metadata knows about
    # them before create_all is called.
    import app.models.sql as _sql_models  # noqa: F401

    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    logger.info("SQLModel tables created (if not exists).")


async def _get_asyncpg_pool() -> Optional[asyncpg.Pool]:
    """Lazy import helper — avoids circular import with connection.py."""
    from app.db.connection import get_pool

    return await get_pool()
