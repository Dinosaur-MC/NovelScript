"""Verify that PK / FK / CHECK / UNIQUE constraints are enforced."""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# 1. Foreign-key violation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fk_violation_rejected(db_conn):
    """Insert into chapters with a non-existent novel_id must fail."""
    fake_novel_id = uuid.uuid4()
    with pytest.raises(Exception):  # asyncpg raises ForeignKeyViolationError
        await db_conn.execute(
            """
            INSERT INTO chapters (novel_id, chapter_index, title)
            VALUES ($1, 1, 'Ghost Chapter')
            """,
            fake_novel_id,
        )


# ---------------------------------------------------------------------------
# 2. CHECK constraint violation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_violation_rejected(db_conn):
    """A task status outside the allowed set must be rejected."""
    # Use a real novel id (create one inline)
    novel_id = uuid.uuid4()
    try:
        await db_conn.execute(
            "INSERT INTO novels (id, title) VALUES ($1, 'CK Novel')",
            novel_id,
        )
        with pytest.raises(Exception):
            await db_conn.execute(
                """
                INSERT INTO tasks (novel_id, status)
                VALUES ($1, 'invalid_status')
                """,
                novel_id,
            )
    finally:
        await db_conn.execute("DELETE FROM novels WHERE id = $1", novel_id)


# ---------------------------------------------------------------------------
# 3. Unique email constraint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unique_email_violation(db_conn):
    """Two users with the same email must be rejected."""
    email = f"dup_{uuid.uuid4().hex[:8]}@test.local"
    user1_id = uuid.uuid4()
    try:
        await db_conn.execute(
            "INSERT INTO users (id, username, email, password_hash) "
            "VALUES ($1, 'u1', $2, 'h')",
            user1_id,
            email,
        )
        with pytest.raises(Exception):
            await db_conn.execute(
                "INSERT INTO users (id, username, email, password_hash) "
                "VALUES ($1, 'u2', $2, 'h')",
                uuid.uuid4(),
                email,
            )
    finally:
        await db_conn.execute("DELETE FROM users WHERE id = $1", user1_id)
