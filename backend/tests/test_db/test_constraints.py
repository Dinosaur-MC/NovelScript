"""Verify PK / FK / CHECK / UNIQUE constraint enforcement."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


def test_fk_violation_rejected(db_conn):
    """Insert into chapters with non-existent novel_id must fail."""
    fake_novel_id = uuid.uuid4()
    with pytest.raises(Exception):
        db_conn.execute(text(
            "INSERT INTO chapters (novel_id, chapter_index, title) "
            "VALUES (:id, 1, 'Ghost Chapter')"
        ), {"id": fake_novel_id})


def test_check_violation_rejected(db_conn):
    """Task status outside allowed set must be rejected."""
    novel_id = uuid.uuid4()
    try:
        db_conn.execute(text(
            "INSERT INTO novels (id, title) VALUES (:id, 'CK Novel')"
        ), {"id": novel_id})
        db_conn.commit()
        with pytest.raises(Exception):
            db_conn.execute(text(
                "INSERT INTO tasks (novel_id, status) "
                "VALUES (:nid, 'invalid_status')"
            ), {"nid": novel_id})
    finally:
        db_conn.rollback()  # reset aborted transaction after constraint violation
        db_conn.execute(text("DELETE FROM tasks WHERE novel_id = :id"), {"id": novel_id})
        db_conn.execute(text("DELETE FROM novels WHERE id = :id"), {"id": novel_id})
        db_conn.commit()


def test_unique_email_violation(db_conn):
    """Two users with same email must be rejected."""
    tag = uuid.uuid4().hex[:8]
    email = f"dup_{tag}@test.local"
    u1 = uuid.uuid4()
    try:
        db_conn.execute(text(
            "INSERT INTO users (id, username, email, password_hash) "
            "VALUES (:id, :uname, :email, 'h')"
        ), {"id": u1, "uname": f"u1_{tag}", "email": email})
        db_conn.commit()
        with pytest.raises(Exception):
            db_conn.execute(text(
                "INSERT INTO users (id, username, email, password_hash) "
                "VALUES (:id, :uname, :email, 'h')"
            ), {"id": uuid.uuid4(), "uname": f"u2_{tag}", "email": email})
    finally:
        db_conn.rollback()  # reset aborted transaction after constraint violation
        db_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": u1})
        db_conn.commit()
