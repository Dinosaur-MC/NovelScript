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
       Indexes are deferred until after v3 column additions.
    3. Add v3.0.0 columns to existing tables (idempotent).
    4. Execute v3 indexes from init.sql.
    5. Create all SQLModel-managed tables (idempotent).
    6. Run v3 migration (backfill scripts from legacy tasks).
    7. Seed admin account.
    """
    logger.info("Initialising database …")

    # -- 1. Extensions — privilege-guarded --------------------------------- #
    with _engine.connect() as conn:
        for ext in ("uuid-ossp", "vector", "pg_trgm"):
            try:
                conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.warning(
                    "Cannot create extension %s: %s. "
                    "If pre-installed by superuser, this is safe.",
                    ext, exc,
                )

    # -- 2. Tables DDL (init.sql minus extensions AND indexes) ------------- #
    sql_path = Path(__file__).resolve().parent.parent / "db" / "init.sql"
    raw_sql = sql_path.read_text(encoding="utf-8")
    lines = raw_sql.splitlines()
    table_lines = []
    index_lines = []
    in_index_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("CREATE EXTENSION"):
            continue
        if stripped.startswith("-- Default Indexes") or stripped.startswith("-- Vector Indexes") or stripped.startswith("-- Trigram Index") or stripped.startswith("-- Composite unique"):
            in_index_section = True
        if stripped.startswith("-- ====") and ("Migration" in stripped or "backfill" in stripped.lower()):
            in_index_section = True  # skip migration block
        if not in_index_section:
            table_lines.append(line)
        else:
            index_lines.append(line)

    with _engine.connect() as conn:
        for statement in _split_statements("\n".join(table_lines)):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()

    logger.info("Tables DDL executed.")

    # -- 3. Add v3.0.0 columns to existing tables (idempotent) ------------- #
    # These must run AFTER the scripts table exists but BEFORE indexes.
    _add_column_if_missing("tasks", "script_id", "UUID REFERENCES scripts(id) ON DELETE SET NULL")
    _add_column_if_missing("knowledge_nodes", "script_id", "UUID REFERENCES scripts(id) ON DELETE CASCADE")
    _add_column_if_missing("knowledge_edges", "script_id", "UUID REFERENCES scripts(id) ON DELETE CASCADE")
    _add_column_if_missing("operations", "script_id", "UUID REFERENCES scripts(id) ON DELETE CASCADE")
    _add_column_if_missing("dialogues", "script_id", "UUID REFERENCES scripts(id) ON DELETE CASCADE")
    _add_column_if_missing("audit_logs", "script_id", "UUID REFERENCES scripts(id) ON DELETE SET NULL")
    _add_column_if_missing("tasks", "token_usage", "JSONB NOT NULL DEFAULT '{}'::jsonb")

    # Make legacy NOT NULL columns nullable for v3 migration
    for tbl, col in [("operations", "task_id"), ("dialogues", "task_id")]:
        try:
            with _engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN {col} DROP NOT NULL"))
                conn.commit()
        except Exception:
            logger.debug("Could not alter %s.%s to nullable (may already be).", tbl, col)

    # -- 4. Indexes DDL --------------------------------------------------- #
    with _engine.connect() as conn:
        for statement in _split_statements("\n".join(index_lines)):
            stmt = statement.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    conn.rollback()
                    logger.debug("Index creation skipped (column may not exist yet).")
        conn.commit()

    logger.info("Indexes DDL executed.")

    # -- 5. SQLModel tables ----------------------------------------------- #
    import app.models.sql as _sql_models  # noqa: F401

    SQLModel.metadata.create_all(_engine)
    logger.info("SQLModel tables created (if not exists).")

    # -- 6. v3 migration + seed admin ------------------------------------- #
    # NOTE: recover_stale_tasks() is intentionally NOT called here.
    # During uvicorn --reload, init_db() runs on every file change, which would
    # mark in-progress tasks (preprocessing/converting) as "failed" — killing
    # the very pipeline the Celery worker is actively executing.  The worker
    # is a sibling process that survives reload; its tasks should not be
    # interrupted.  Call recover_stale_tasks() manually if needed, or via a
    # dedicated admin endpoint.
    _migrate_v3()
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
    """Split SQL on semicolons, yielding non-empty, non-comment statements."""
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Skip pure-comment blocks (e.g. separator headers)
        if all(
            line.strip().startswith("--") or line.strip() == ""
            for line in stmt.splitlines()
            if line.strip()
        ):
            continue
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


def _migrate_v3() -> None:
    """Backfill scripts table from legacy task-embedded script data.

    Idempotent — only runs when scripts table exists but is empty, and
    there are legacy tasks with script_yaml/script_json artifacts.
    """
    from sqlalchemy import text as sa_text

    migration_sql = """
    DO $$
    DECLARE
        _rec RECORD;
        _sid UUID;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM scripts LIMIT 1) THEN
            FOR _rec IN
                SELECT *
                FROM tasks
                WHERE script_yaml IS NOT NULL OR script_json IS NOT NULL
            LOOP
                _sid := gen_random_uuid();
                INSERT INTO scripts (
                    id, novel_id, user_id, title, source_type, status,
                    summary, script_yaml, script_json, script_fountain,
                    characters_json, token_usage, created_at, updated_at
                ) VALUES (
                    _sid, _rec.novel_id, _rec.user_id,
                    COALESCE(_rec.summary, 'Script'), 'generated',
                    CASE WHEN _rec.status = 'completed' THEN 'completed' ELSE 'editing' END,
                    _rec.summary,
                    _rec.script_yaml, _rec.script_json, _rec.script_fountain,
                    _rec.characters_json, _rec.token_usage,
                    _rec.created_at, now()
                );
                UPDATE tasks SET script_id = _sid WHERE id = _rec.id;
            END LOOP;
        END IF;
    END $$;
    """

    try:
        with _engine.connect() as conn:
            conn.execute(sa_text(migration_sql))
            conn.commit()
        logger.info("v3.0.0 migration: scripts backfill completed.")
    except Exception:
        logger.debug("v3.0.0 migration skipped (may already be applied or table missing).")
