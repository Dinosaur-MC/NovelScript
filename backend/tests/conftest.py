"""Shared pytest fixtures for the NovelScript backend test suite."""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import _engine, _async_session_factory, init_db
from app.db.connection import close_pool, get_pool

# Let pytest-asyncio manage the event loop natively (no custom event_loop fixture).
# On Windows this avoids "different loop" errors with ProactorEventLoop.
pytest_plugins = ("pytest_asyncio",)

# ---------------------------------------------------------------------------
# Database fixtures — one init per module to amortize setup cost
# ---------------------------------------------------------------------------

_initialised: bool = False


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    """Initialise the database once per test module."""
    global _initialised
    if not _initialised:
        await init_db()
        _initialised = True
    yield
    # Cleanup is handled at the module level by the last test finishing.
    # We skip engine disposal here to keep it alive across modules.


@pytest_asyncio.fixture
async def db_conn(db_engine: None):
    """Raw asyncpg connection for DDL / constraint tests."""
    pool = await get_pool()
    if pool is None:
        pytest.skip("asyncpg pool not available — is PostgreSQL running?")
    async with pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture
async def db(db_engine: None) -> AsyncGenerator[AsyncSession, None]:
    """SQLAlchemy AsyncSession for ORM tests."""
    async with _async_session_factory() as session:  # type: ignore[attr-defined]
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user_data():
    """Return a dict suitable for User creation without hitting the DB."""
    uid = uuid.uuid4()
    name = f"testuser_{uid.hex[:8]}"
    return {
        "id": uid,
        "username": name,
        "email": f"{name}@test.local",
        "password_hash": "fake_hash",
    }
