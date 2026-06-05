"""Shared pytest fixtures — all synchronous, no event-loop issues."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.db import _engine, _session_factory, init_db

_DB_INITIALISED: bool = False


@pytest.fixture(scope="session")
def db_engine():
    """Initialise the database once per test session."""
    global _DB_INITIALISED
    if not _DB_INITIALISED:
        init_db()
        _DB_INITIALISED = True
    yield
    # Engine is disposed by pytest's built-in cleanup


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
