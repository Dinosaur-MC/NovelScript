"""Database connection utilities — sync-only, no asyncpg.

Uses SQLAlchemy's raw connection for DDL execution.  No more event-loop
headaches on Windows.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, text

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine = create_engine(
    settings.DATABASE_URL.replace("+asyncpg", "").replace("+psycopg", ""),
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
)


def get_raw_connection():
    """Return a raw DB-API 2.0 connection (for DDL / arbitrary SQL)."""
    return _engine.raw_connection()


def execute_raw_sql(sql: str) -> None:
    """Execute raw SQL (DDL, extensions, indexes) via SQLAlchemy engine."""
    conn = _engine.connect()
    try:
        # Execute each statement separately — CREATE EXTENSION etc.
        for statement in _split_statements(sql):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    finally:
        conn.close()


def _split_statements(sql: str):
    """Split SQL text on semicolons, respecting basic quoting."""
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            yield stmt


def dispose_engine() -> None:
    """Close all connections in the engine pool."""
    _engine.dispose()
