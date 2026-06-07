"""Database lifecycle — sync session dependency and initialisation."""

from __future__ import annotations

import atexit
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
    pool_pre_ping=True,   # verify connections are alive before using
    pool_recycle=3600,    # recycle connections after 1 hour
)

_session_factory = sessionmaker(
    _engine,
    class_=Session,
    expire_on_commit=False,
)


def dispose_engine() -> None:
    """Close the connection pool, releasing all idle connections.

    Call this at application shutdown or process exit.  Safe to call
    multiple times — subsequent calls are no-ops.
    """
    logger.info("Disposing database engine pool …")
    _engine.dispose()


atexit.register(dispose_engine)


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
                conn.commit()  # commit immediately so failure doesn't undo prior successes
            except Exception as exc:
                conn.rollback()  # clear aborted transaction
                logger.warning(
                    "Cannot create extension %s: %s. "
                    "If pre-installed by superuser, this is safe.",
                    ext, exc,
                )

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

    # -- 3b. Lightweight column additions (no full migration framework) ----- #
    _add_column_if_missing("tasks", "token_usage", "JSONB NOT NULL DEFAULT '{}'::jsonb")

    # -- 4. Recover stale tasks from previous run ------------------------- #
    from app.services.pipeline_executor import recover_stale_tasks

    recover_stale_tasks()

    # -- 5. Seed initial admin account ------------------------------------ #
    _seed_admin()


def _add_column_if_missing(table: str, column: str, col_def: str) -> None:
    """Add *column* to *table* if it doesn't already exist.

    PostgreSQL does not support ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``,
    so we probe ``information_schema.columns`` first.
    """
    try:
        with _engine.connect() as conn:
            # Check if column already exists
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :tbl AND column_name = :col"
                ),
                {"tbl": table, "col": column},
            ).first()
            if row is not None:
                logger.debug("Column %s.%s already exists — skipped.", table, column)
                return
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
            conn.commit()
        logger.info("Column %s.%s added.", table, column)
    except Exception:
        conn.rollback()
        logger.debug("Column %s.%s migration skipped (may already exist).", table, column)


def _split_statements(sql: str):
    """Split SQL on semicolons, yielding non-empty statements."""
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            yield stmt


def _seed_admin() -> None:
    """Create or promote the initial admin account.

    Credentials are read from :class:`Settings` (env vars / .env).

    Strategy (in order):
    1. If a user with ``role='admin'`` AND the configured username already
       exists → skip (already seeded).
    2. If a user with the configured username exists but is NOT admin →
       promote it to admin (the user was created via normal registration
       but is meant to be the administrator).
    3. Otherwise, create a fresh admin row.
    """
    from sqlalchemy import update
    from app.core.security import hash_password
    from app.models.sql import User

    with _session_factory() as session:
        # Check whether an admin with this username already exists
        existing = session.query(User).filter(
            User.username == settings.ADMIN_USERNAME,
            User.role == "admin",
        ).first()
        if existing is not None:
            logger.debug("Admin account %s already exists — skipping seed.", settings.ADMIN_USERNAME)
            session.close()
            return

        # Check whether a non-admin user with this username exists
        regular = session.query(User).filter(
            User.username == settings.ADMIN_USERNAME,
        ).first()
        if regular is not None:
            # Promote to admin
            session.execute(
                update(User)
                .where(User.id == regular.id)
                .values(role="admin", email=settings.ADMIN_EMAIL)
            )
            session.commit()
            logger.info(
                "Promoted existing user %s to admin (email: %s).",
                settings.ADMIN_USERNAME,
                settings.ADMIN_EMAIL,
            )
            session.close()
            return

        # Fresh insert
        admin = User(
            email=settings.ADMIN_EMAIL,
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            display_name=settings.ADMIN_DISPLAY_NAME,
            role="admin",
            is_active=True,
        )
        session.add(admin)
        session.commit()
        logger.info(
            "Seeded admin account: %s <%s>",
            settings.ADMIN_USERNAME,
            settings.ADMIN_EMAIL,
        )
