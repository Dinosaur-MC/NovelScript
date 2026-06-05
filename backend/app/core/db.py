"""Database lifecycle — sync session dependency and initialisation."""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_engine_url(raw_url: str) -> str:
    """Build a URL-safe connection string, encoding user/password components.

    psycopg2's ``make_dsn()`` chokes on non-ASCII bytes in the password
    (common when the .env file was written from a Chinese-locale shell).
    Using SQLAlchemy's URL object with percent-encoded components avoids this.
    """
    # Strip driver prefix if present
    url = raw_url.replace("+asyncpg", "").replace("+psycopg", "")
    parsed = urllib.parse.urlparse(url)
    encoded_user = urllib.parse.quote(parsed.username or "", safe="")
    encoded_pass = urllib.parse.quote(parsed.password or "", safe="")
    encoded_netloc = (
        f"{encoded_user}:{encoded_pass}@{parsed.hostname}"
        + (f":{parsed.port}" if parsed.port else "")
    )
    return parsed._replace(netloc=encoded_netloc).geturl()


# ---------------------------------------------------------------------------
# SQLAlchemy engine (sync — no event-loop issues on Windows)
# ---------------------------------------------------------------------------
_engine = create_engine(
    _build_engine_url(settings.DATABASE_URL),
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
)

_session_factory = sessionmaker(
    _engine,
    class_=Session,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """Yield a :class:`Session` per request."""
    with _session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Full database initialisation.

    1. Create extensions (privilege-guarded).
    2. Execute init.sql for tables, indexes, CHECK constraints.
    3. Create all SQLModel-managed tables (idempotent).
    """
    logger.info("Initialising database …")

    # -- 1. Extensions — privilege-guarded --------------------------------- #
    with _engine.connect() as conn:
        for ext in ("uuid-ossp", "vector", "pg_trgm"):
            try:
                conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
            except Exception as exc:
                logger.warning(
                    "Cannot create extension %s: %s. "
                    "If pre-installed by superuser, this is safe.",
                    ext, exc,
                )
        conn.commit()

    # -- 2. Raw DDL (init.sql minus extensions) --------------------------- #
    sql_path = Path(__file__).resolve().parent.parent / "db" / "init.sql"
    raw_sql = sql_path.read_text(encoding="utf-8")
    skip_extensions_sql = "\n".join(
        line
        for line in raw_sql.splitlines()
        if not line.strip().startswith("CREATE EXTENSION")
    )

    with _engine.connect() as conn:
        for statement in _split_statements(skip_extensions_sql):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()

    logger.info("DDL executed.")

    # -- 3. SQLModel tables ----------------------------------------------- #
    import app.models.sql as _sql_models  # noqa: F401

    SQLModel.metadata.create_all(_engine)
    logger.info("SQLModel tables created (if not exists).")


def _split_statements(sql: str):
    """Split SQL on semicolons, yielding non-empty statements."""
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            yield stmt
