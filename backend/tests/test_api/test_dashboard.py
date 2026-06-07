"""Tests for GET /api/v1/tasks/dashboard — user-scoped aggregation endpoint."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import _session_factory
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.sql import Novel, Script, Task, User

DASHBOARD_URL = "/api/v1/tasks/dashboard"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dashboard_user_id(db_engine) -> str:
    """Create a dedicated test user for dashboard tests and return its ID."""
    _TEST_EMAIL = "dashboard_test@novelscript.test"
    with _session_factory() as session:
        user = session.query(User).filter(User.email == _TEST_EMAIL).first()
        if user is None:
            user = User(
                email=_TEST_EMAIL,
                username="dashboard_tester",
                password_hash=hash_password("test1234"),
                display_name="Dashboard Tester",
                role="user",
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        uid = str(user.id)
    return uid


@pytest.fixture(scope="module")
def auth_headers(db_engine, dashboard_user_id: str) -> dict[str, str]:
    """Return Authorization header with valid JWT."""
    token = create_access_token(dashboard_user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(redis_client) -> TestClient:
    """FastAPI test client with fakeredis override."""
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seed_data(dashboard_user_id: str):
    """Seed novels, scripts, and tasks for the test user — cleaned up after."""
    uid = uuid.UUID(dashboard_user_id)
    with _session_factory() as session:
        n1 = Novel(user_id=uid, title="三体", author="刘慈欣", word_count=200000)
        n2 = Novel(user_id=uid, title="流浪地球", author="刘慈欣", word_count=50000)
        session.add_all([n1, n2])
        session.flush()

        session.add_all([
            Script(user_id=uid, title="剧本A", source_type="generated",
                   script_json={"scenes": [{"scene_id": "s_0001"}, {"scene_id": "s_0002"}]}),
            Script(user_id=uid, title="剧本B", source_type="forked"),
            Script(user_id=uid, title="剧本C", source_type="standalone",
                   script_json={"scenes": [{"scene_id": "s_0001"}]}),
        ])
        session.flush()

        for status, progress in [
            ("completed", 100), ("completed", 100),
            ("converting", 60), ("preprocessing", 15), ("failed", 30),
        ]:
            session.add(Task(novel_id=n1.id, user_id=uid, status=status, progress=progress))
        session.commit()

    yield

    with _session_factory() as session:
        session.query(Task).filter(Task.user_id == uid).delete()
        session.query(Script).filter(Script.user_id == uid).delete()
        session.query(Novel).filter(Novel.user_id == uid).delete()
        session.commit()


# ===================================================================
# Tests
# ===================================================================


def test_requires_auth(client: TestClient) -> None:
    resp = client.get(DASHBOARD_URL)
    assert resp.status_code == 401, resp.text


def test_empty_dashboard(client: TestClient, auth_headers: dict) -> None:
    resp = client.get(DASHBOARD_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["stats"] == {
        "novels": 0, "scripts": 0,
        "in_progress": 0, "completed": 0, "failed": 0,
    }
    assert data["recent_tasks"] == []
    assert data["recent_scripts"] == []
    assert data["recent_novels"] == []


def test_dashboard_stats(
    client: TestClient, auth_headers: dict, seed_data
) -> None:
    resp = client.get(DASHBOARD_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    stats = resp.json()["data"]["stats"]
    assert stats["novels"] == 2
    assert stats["scripts"] == 3
    assert stats["in_progress"] == 2
    assert stats["completed"] == 2
    assert stats["failed"] == 1


def test_recent_tasks_shape(
    client: TestClient, auth_headers: dict, seed_data
) -> None:
    resp = client.get(DASHBOARD_URL, headers=auth_headers)
    tasks = resp.json()["data"]["recent_tasks"]
    assert len(tasks) == 5
    t = tasks[0]
    assert "task_id" in t
    assert "script_id" in t  # may be null
    assert "novel_title" in t
    assert t["novel_title"] == "三体"
    assert t["status"] == "failed"  # most recently created


def test_recent_scripts_shape(
    client: TestClient, auth_headers: dict, seed_data
) -> None:
    resp = client.get(DASHBOARD_URL, headers=auth_headers)
    scripts = resp.json()["data"]["recent_scripts"]
    assert len(scripts) == 3
    sa = next(s for s in scripts if "A" in s["title"])
    assert sa["scene_count"] == 2
    assert sa["source_type"] == "generated"
    sb = next(s for s in scripts if "B" in s["title"])
    assert sb["scene_count"] == 0


def test_recent_novels_shape(
    client: TestClient, auth_headers: dict, seed_data
) -> None:
    resp = client.get(DASHBOARD_URL, headers=auth_headers)
    novels = resp.json()["data"]["recent_novels"]
    assert len(novels) == 2
    for n in novels:
        assert "id" in n
        assert "title" in n
        assert "word_count" in n
        assert "status" in n


def test_user_isolation(
    client: TestClient, auth_headers: dict
) -> None:
    other_id = uuid.uuid4()
    with _session_factory() as session:
        session.add(Novel(id=other_id, user_id=None, title="别人的小说"))
        session.commit()
    try:
        resp = client.get(DASHBOARD_URL, headers=auth_headers)
        assert resp.json()["data"]["stats"]["novels"] == 0
    finally:
        with _session_factory() as session:
            n = session.get(Novel, other_id)
            if n:
                session.delete(n)
                session.commit()
