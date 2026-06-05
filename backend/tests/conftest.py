"""Shared pytest fixtures for the NovelScript backend test suite."""

from __future__ import annotations

from typing import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import _engine, _async_session_factory, init_db
from app.db.connection import get_pool

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

_DB_INITIALISED: bool = False


@pytest_asyncio.fixture(loop_scope="module")
async def db_engine():
    """Initialise DB per module.  loop_scope="module" ensures all tests in
    the module share one event loop.  init_db() closes any stale pool
    from a previous module before creating a fresh one."""
    await init_db()
    yield


@pytest_asyncio.fixture(loop_scope="module")
async def db_conn(db_engine: None):
    """Raw asyncpg connection for DDL / constraint tests."""
    pool = await get_pool()
    if pool is None:
        import pytest
        pytest.skip("asyncpg pool not available — is PostgreSQL running?")
    async with pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture(loop_scope="module")
async def db(db_engine: None) -> AsyncGenerator[AsyncSession, None]:
    """SQLAlchemy AsyncSession for ORM tests."""
    async with _async_session_factory() as session:  # type: ignore[attr-defined]
        yield session
        await session.rollback()
