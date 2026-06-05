"""Shared pytest fixtures for the NovelScript backend test suite."""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.db import _engine, _async_session_factory, init_db
from app.db.connection import close_pool, get_pool


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database-level fixtures (require a running PostgreSQL)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Initialise the database (extensions, tables, indexes) once per session."""
    await init_db()
    yield
    await close_pool()
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_conn(db_engine: None):
    """Provide a raw asyncpg connection for DDL / constraint tests."""
    pool = await get_pool()
    if pool is None:
        pytest.skip("asyncpg pool not available — is PostgreSQL running?")
    async with pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture
async def db(db_engine: None) -> AsyncGenerator[AsyncSession, None]:
    """Provide a SQLAlchemy :class:`AsyncSession` for ORM tests."""
    async with _async_session_factory() as session:  # type: ignore[attr-defined]
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_user(db: AsyncSession) -> dict:
    """Insert a minimal test user and return its dict representation.

    The row is rolled back automatically by the ``db`` fixture.
    """
    from app.models.sql import User

    uid = uuid.uuid4()
    username = f"testuser_{uid.hex[:8]}"
    user = User(
        id=uid,
        username=username,
        email=f"{username}@test.local",
        password_hash="fake_hash",
    )
    db.add(user)
    await db.flush()
    return {
        "id": uid,
        "username": username,
        "email": f"{username}@test.local",
    }
