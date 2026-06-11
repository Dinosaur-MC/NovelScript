"""Shared pytest fixtures — all synchronous, no event-loop issues."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

import fakeredis
from sqlmodel import SQLModel

from app.core.db import _engine, _session_factory, init_db
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.models.sql import User

_DB_INITIALISED: bool = False

# Shared test user credentials — created once per session in db fixture
_TEST_USER_EMAIL = "testrunner@novelscript.test"
_TEST_USER_PASSWORD = "testrunner1234"


@pytest.fixture(scope="session", autouse=True)
def _mock_celery_and_redis():
    """Prevent Celery + background watchers from connecting during tests.

    Mocks:
    1. ``run_pipeline.apply_async`` — Celery dispatch becomes no-op.
    2. ``get_redis_client`` — background watcher uses this directly (not the
       FastAPI ``get_redis`` dependency). Without this mock it would try to
       connect to real Redis and hang.
    3. ``simple_queue.worker_loop`` — its ``BRPOP`` call is a synchronous
       blocking operation that would block the TestClient's event loop,
       causing all tests to hang indefinitely.
    """
    with (
        patch("app.tasks.pipeline.run_pipeline.apply_async"),
        patch("app.core.redis.get_redis_client") as mock_get_client,
        patch("app.services.simple_queue.worker_loop"),
    ):
        fake = fakeredis.FakeRedis(decode_responses=True)
        mock_get_client.return_value = fake
        yield


@pytest.fixture(scope="session")
def db_engine():
    """Initialise the database once per test session.

    Uses `SQLModel.metadata.create_all()` instead of the full ``init_db()``
    — much faster because it skips:
    - Extension creation (assumes uuid-ossp, vector, pg_trgm exist)
    - init.sql DDL parsing and execution
    - v3 migration backfill
    - Admin account seeding

    Tables are only created if they don't exist (idempotent).
    """
    global _DB_INITIALISED
    if not _DB_INITIALISED:
        # Fast idempotent table creation — no DDL parsing
        import app.models.sql as _sql_models  # noqa: F401
        SQLModel.metadata.create_all(_engine)
        _DB_INITIALISED = True
    yield
    # Dispose engine pool so connections don't linger after tests
    from app.core.db import dispose_engine

    dispose_engine()


@pytest.fixture
def db_conn(db_engine: None):
    """Raw DB-API connection for DDL / constraint tests."""
    conn = _engine.connect()
    yield conn
    conn.close()


@pytest.fixture
def db(db_engine: None):
    """SQLAlchemy Session for ORM tests — auto-rollback on teardown."""
    with _session_factory() as session:
        yield session
        session.rollback()


@pytest.fixture
def redis_client():
    """In-memory fakeredis — isolated per test function."""
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.flushall()


# ---------------------------------------------------------------------------
# Auth helpers — get a valid JWT for API tests that require Bearer auth
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers(db: Session) -> dict[str, str]:
    """Return ``{"Authorization": "Bearer <jwt>"}`` for a test user.

    The user is created via the ``db`` fixture (rollback session for
    tests with ``get_db`` override; real session for bare ``TestClient``).
    A JWT is minted directly — no login API call needed.
    """
    user = db.query(User).filter(User.email == _TEST_USER_EMAIL).first()
    if user is None:
        user = User(
            email=_TEST_USER_EMAIL,
            username="testrunner",
            password_hash=hash_password(_TEST_USER_PASSWORD),
            display_name="Test Runner",
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.refresh(user)

    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}
