"""Tests for Task Management API (Agent F) — 6 test cases.

Requires a running PostgreSQL instance configured via ``DATABASE_URL``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import _session_factory, get_db
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.sql import AuditLog, Novel, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_novel_id(db_engine):
    """Create a novel for test task operations."""
    nid: uuid.UUID = uuid.uuid4()
    with _session_factory() as session:
        novel = Novel(
            id=nid,
            title="Test Novel for Tasks API",
            word_count=5000,
        )
        session.add(novel)
        session.commit()

    yield str(nid)

    with _session_factory() as session:
        novel = session.get(Novel, nid)
        if novel is not None:
            session.delete(novel)
            session.commit()


@pytest.fixture(scope="module")
def auth_headers(db_engine) -> dict[str, str]:
    """Return auth headers by creating a test user directly in the real DB.

    Module-scoped so all 6 tests share one user.  Uses a dedicated
    session (not the rollback fixture) because this test file does
    not override ``get_db`` — the API reads from real sessions.
    """
    _TEST_EMAIL = "task_test@novelscript.test"
    with _session_factory() as session:
        user = session.query(User).filter(User.email == _TEST_EMAIL).first()
        if user is None:
            user = User(
                email=_TEST_EMAIL,
                username="task_tester",
                password_hash=hash_password("test1234"),
                display_name="Task Tester",
                role="admin",
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)

        token = create_access_token(str(user.id))

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(redis_client) -> TestClient:
    """FastAPI synchronous test client with fakeredis override."""
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ===================================================================
# Test 1 — POST /api/tasks  (create with valid novel)
# ===================================================================


def test_create_task(client: TestClient, test_novel_id: str, auth_headers: dict) -> None:
    """Create a task and verify the response shape."""
    resp = client.post("/api/v1/tasks/", json={"novel_id": test_novel_id}, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["code"] == 200
    assert body["message"] == "Task created"
    assert "task_id" in body["data"]
    assert body["data"]["status"] == "pending"

    # Also verify the lightweight status endpoint
    task_id = body["data"]["task_id"]
    status_resp = client.get(f"/api/v1/tasks/{task_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["status"] == "pending"
    assert status_resp.json()["data"]["progress"] == 0


# ===================================================================
# Test 2 — POST /api/tasks with non-existent novel → 404
# ===================================================================


def test_create_task_invalid_novel_404(
    client: TestClient, auth_headers: dict
) -> None:
    """Creating a task for a novel that does not exist returns 404."""
    fake_id = str(uuid.uuid4())
    resp = client.post("/api/v1/tasks/", json={"novel_id": fake_id}, headers=auth_headers)
    assert resp.status_code == 404, resp.text


# ===================================================================
# Test 3 — PUT /api/tasks/{id}/status  valid chain
# ===================================================================


def test_valid_status_transition(
    client: TestClient, test_novel_id: str, auth_headers: dict
) -> None:
    """Exercise the full happy path: pending→preprocessing→converting→completed."""
    # Create
    resp = client.post("/api/v1/tasks/", json={"novel_id": test_novel_id}, headers=auth_headers)
    assert resp.status_code == 200
    task_id: str = resp.json()["data"]["task_id"]

    # pending → preprocessing
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "preprocessing", "progress": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "preprocessing"
    assert resp.json()["data"]["progress"] == 10

    # preprocessing → converting
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status", json={"status": "converting", "progress": 50},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "converting"

    # converting → completed
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status", json={"status": "completed", "progress": 100},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"
    assert resp.json()["data"]["progress"] == 100

    # Verify the detail endpoint reflects the final state
    detail = client.get(f"/api/v1/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "completed"
    assert detail.json()["data"]["progress"] == 100


# ===================================================================
# Test 4 — PUT /api/tasks/{id}/status  skip-stage → 422
# ===================================================================


def test_invalid_skip_transition_422(
    client: TestClient, test_novel_id: str, auth_headers: dict
) -> None:
    """Jumping from pending straight to completed must return 422."""
    resp = client.post("/api/v1/tasks/", json={"novel_id": test_novel_id}, headers=auth_headers)
    assert resp.status_code == 200
    task_id: str = resp.json()["data"]["task_id"]

    # pending → completed is NOT a valid direct transition
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status", json={"status": "completed"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text

    # The task should still be pending
    status = client.get(f"/api/v1/tasks/{task_id}/status")
    assert status.json()["data"]["status"] == "pending"


# ===================================================================
# Test 5 — POST /api/tasks/{id}/resume
# ===================================================================


def test_resume_from_failed(
    client: TestClient, test_novel_id: str, auth_headers: dict
) -> None:
    """A failed task can be resumed (failed → converting)."""
    resp = client.post("/api/v1/tasks/", json={"novel_id": test_novel_id}, headers=auth_headers)
    assert resp.status_code == 200
    task_id: str = resp.json()["data"]["task_id"]

    # pending → failed
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "failed", "error_message": "Simulated crash"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "failed"

    # Resume
    resp = client.post(f"/api/v1/tasks/{task_id}/resume", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "converting"

    # error_message must be cleared on resume
    status = client.get(f"/api/v1/tasks/{task_id}/status")
    assert status.json()["data"]["error_message"] is None

    # Resume a non-failed task → 422
    resp2 = client.post(f"/api/v1/tasks/{task_id}/resume", headers=auth_headers)
    assert resp2.status_code == 422


# ===================================================================
# Test 6 — Audit log written on every status change
# ===================================================================


def test_audit_log_written(
    client: TestClient, test_novel_id: str, auth_headers: dict
) -> None:
    """Every status transition must persist an AuditLog row."""
    resp = client.post("/api/v1/tasks/", json={"novel_id": test_novel_id}, headers=auth_headers)
    assert resp.status_code == 200
    task_id: str = resp.json()["data"]["task_id"]
    tid: uuid.UUID = uuid.UUID(task_id)

    # Perform a status change
    resp = client.put(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "failed", "error_message": "Intentional failure"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Query the audit_logs table directly
    from sqlalchemy import select

    with _session_factory() as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.task_id == tid)
            .where(AuditLog.category == "task_status")
            .order_by(AuditLog.created_at.desc())
        )
        logs = session.execute(stmt).scalars().all()

    assert len(logs) >= 1, "Expected at least one audit log entry"
    latest = logs[0]
    assert latest.level == "info"
    assert latest.category == "task_status"
    assert "pending" in latest.message
    assert "failed" in latest.message
    assert latest.detail == {"from": "pending", "to": "failed"}
