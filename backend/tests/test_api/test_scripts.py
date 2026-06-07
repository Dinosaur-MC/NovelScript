"""Tests for Script Management API (Agent E)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import _session_factory, get_db
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.models.sql import User

_SCRIPTS_TEST_EMAIL = "script_test@novelscript.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ensure_test_user(session) -> User:
    """Find or create the scripts test user in *session*, return it."""
    user = session.query(User).filter(User.email == _SCRIPTS_TEST_EMAIL).first()
    if user is None:
        user = User(
            email=_SCRIPTS_TEST_EMAIL,
            username="script_tester",
            password_hash=hash_password("test1234"),
            display_name="Script Tester",
            role="admin",
            is_active=True,
        )
        session.add(user)
        session.flush()
    return user


@pytest.fixture
def client_and_session(db_engine, redis_client):
    """TestClient + test Session + auth headers for script mutating tests."""
    from app.main import app

    with _session_factory() as test_session:
        user = _ensure_test_user(test_session)
        token = create_access_token(str(user.id))
        auth_headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            yield test_session

        def _override_get_redis():
            yield redis_client

        app.dependency_overrides[get_db] = _get_test_db
        app.dependency_overrides[get_redis] = _override_get_redis

        with TestClient(app) as tc:
            yield (tc, test_session, auth_headers)

        app.dependency_overrides.clear()
        test_session.rollback()


@pytest.fixture
def client(db, redis_client):
    """TestClient with get_db override (for GET and public endpoints)."""
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers_scripts(db):
    """Auth headers for tests that use the ``client`` fixture (conftest db)."""
    user = _ensure_test_user(db)
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_novel(session, **kwargs) -> uuid.UUID:
    from app.models.sql import Novel

    novel = Novel(
        id=kwargs.pop("id", uuid.uuid4()),
        title=kwargs.pop("title", "Test Novel"),
        author=kwargs.pop("author", "Test Author"),
        **kwargs,
    )
    session.add(novel)
    session.flush()
    return novel.id


def _make_task(session, novel_id: uuid.UUID, **kwargs) -> uuid.UUID:
    from app.models.sql import Task

    task = Task(
        id=kwargs.pop("id", uuid.uuid4()),
        novel_id=novel_id,
        status=kwargs.pop("status", "completed"),
        progress=kwargs.pop("progress", 100),
        **kwargs,
    )
    session.add(task)
    session.flush()
    return task.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_scripts(client, db):
    """GET /api/scripts/ — list scripts with filters and scene_count."""
    nid = _make_novel(db, title="List Test Novel")
    tid = _make_task(db, nid, script_json={"scenes": [{"id": 1}, {"id": 2}, {"id": 3}]})
    db.flush()

    # List all scripts
    resp = client.get("/api/v1/scripts/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["total"] >= 1
    items = body["data"]["items"]
    script_ids = [i["script_id"] for i in items]
    assert str(tid) in script_ids

    our = next(i for i in items if i["script_id"] == str(tid))
    assert our["scene_count"] == 3

    resp2 = client.get(f"/api/v1/scripts/?novel_id={nid}")
    assert resp2.status_code == 200
    items2 = resp2.json()["data"]["items"]
    assert all(i["novel_id"] == str(nid) for i in items2)

    resp3 = client.get("/api/v1/scripts/?status=completed")
    assert resp3.status_code == 200
    items3 = resp3.json()["data"]["items"]
    assert all(i["status"] == "completed" for i in items3)

    resp4 = client.get("/api/v1/scripts/?page=1&limit=1")
    assert resp4.status_code == 200
    assert resp4.json()["data"]["limit"] == 1
    assert resp4.json()["data"]["page"] == 1


def test_get_script(client, db):
    """GET /api/scripts/{task_id} — return full script data."""
    nid = _make_novel(db, title="Get Test Novel")
    tid = _make_task(
        db, nid,
        script_yaml="scenes:\n  - id: 1\n    heading: Opening",
        script_json={"scenes": [{"id": 1, "heading": "Opening"}]},
        script_fountain="INT. ROOM - DAY\n\nHello world!",
        characters_json={"hero": {"name": "John", "age": 30}},
    )
    db.flush()

    resp = client.get(f"/api/v1/scripts/{tid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["script_id"] == str(tid)
    assert data["novel_id"] == str(nid)
    assert data["status"] == "completed"
    assert data["script_yaml"] == "scenes:\n  - id: 1\n    heading: Opening"
    assert data["script_json"] == {"scenes": [{"id": 1, "heading": "Opening"}]}
    assert data["script_fountain"] == "INT. ROOM - DAY\n\nHello world!"
    assert data["characters_json"] == {"hero": {"name": "John", "age": 30}}

    resp404 = client.get(f"/api/v1/scripts/{uuid.uuid4()}")
    assert resp404.status_code == 404


def test_put_valid_yaml(client_and_session):
    """PUT /api/scripts/{task_id} — update with valid YAML, create Operation."""
    tc, test_session, auth_headers = client_and_session
    nid = _make_novel(test_session, title="Put Valid Test")
    tid = _make_task(test_session, nid, script_yaml="original: value")
    test_session.commit()

    valid_yaml = "scenes:\n  - id: 1\n    heading: Updated Scene\n    dialogue:\n      - character: ALICE\n        line: Hello"
    resp = tc.put(
        f"/api/v1/scripts/{tid}",
        json={"script_yaml": valid_yaml},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["script_id"] == str(tid)
    assert data["updated_at"] is not None
    assert data["validation"]["valid"] is True
    assert data["validation"]["errors"] is None

    resp_get = tc.get(f"/api/v1/scripts/{tid}")
    assert resp_get.status_code == 200
    assert resp_get.json()["data"]["script_yaml"] == valid_yaml

    from app.models.sql import Operation
    test_session.commit()
    ops = test_session.query(Operation).filter(Operation.task_id == tid).all()
    assert len(ops) >= 1
    assert ops[-1].type == "manual_edit"
    assert ops[-1].target_path == "/script_yaml"


def test_put_invalid_yaml_422(client, db, auth_headers_scripts):
    """PUT /api/scripts/{task_id} — invalid YAML returns 422."""
    nid = _make_novel(db, title="Put Invalid Test")
    tid = _make_task(db, nid)
    db.flush()

    invalid_yaml = "scenes:\n\t- id: 1"
    resp = client.put(
        f"/api/v1/scripts/{tid}",
        json={"script_yaml": invalid_yaml},
        headers=auth_headers_scripts,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "Invalid YAML" in body.get("detail", "")


def test_export(client, db):
    """GET /api/scripts/{task_id}/export — raw text in yaml/json/fountain."""
    sample_yaml = "scenes:\n  - id: 1\n    heading: Export Test"
    sample_json = {"scenes": [{"id": 1, "heading": "Export Test"}]}
    sample_fountain = "INT. OFFICE - DAY\n\nTesting export."
    nid = _make_novel(db, title="Export Test")
    tid = _make_task(
        db, nid,
        script_yaml=sample_yaml,
        script_json=sample_json,
        script_fountain=sample_fountain,
    )
    db.flush()

    resp_yaml = client.get(f"/api/v1/scripts/{tid}/export?format=yaml")
    assert resp_yaml.status_code == 200
    assert resp_yaml.text == sample_yaml

    resp_json = client.get(f"/api/v1/scripts/{tid}/export?format=json")
    assert resp_json.status_code == 200
    parsed = json.loads(resp_json.text)
    assert parsed == sample_json

    resp_fountain = client.get(f"/api/v1/scripts/{tid}/export?format=fountain")
    assert resp_fountain.status_code == 200
    assert resp_fountain.text == sample_fountain

    resp404 = client.get(f"/api/v1/scripts/{uuid.uuid4()}/export?format=yaml")
    assert resp404.status_code == 404

    resp_bad = client.get(f"/api/v1/scripts/{tid}/export?format=invalid")
    assert resp_bad.status_code == 422
