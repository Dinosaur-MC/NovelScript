"""Database connection utilities — sync-only.

Shares the engine from ``app.core.db``.  No separate pool needed.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_raw_connection():
    """Return a raw DB-API 2.0 connection (for DDL / arbitrary SQL)."""
    from app.core.db import _engine
    return _engine.raw_connection()


def execute_raw_sql(sql: str) -> None:
    """Execute raw SQL (DDL, extensions, indexes) via the shared engine."""
    from app.core.db import _engine

    conn = _engine.connect()
    try:
        for statement in _split_statements(sql):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    finally:
        conn.close()


def _split_statements(sql: str):
    """Split SQL text on semicolons, yielding non-empty statements."""
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            yield stmt


def dispose_engine() -> None:
    """Close all connections in the engine pool."""
    from app.core.db import _engine
    _engine.dispose()
