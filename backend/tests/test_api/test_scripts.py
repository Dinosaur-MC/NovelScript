"""Tests for Script Management API (Agent E)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import _session_factory, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_and_session(db_engine):
    """TestClient + test Session tuple with overridden get_db.

    All API changes happen inside the same uncommitted transaction.
    Callers receive ``(client, session)`` so they can verify DB state
    within the same transaction as the API handlers.
    """
    from app.main import app

    with _session_factory() as test_session:

        def _get_test_db():
            yield test_session

        app.dependency_overrides[get_db] = _get_test_db

        with TestClient(app) as tc:
            yield tc, test_session

        app.dependency_overrides.clear()
        test_session.rollback()


@pytest.fixture
def client(client_and_session):
    """Shorthand fixture returning just the TestClient."""
    tc, _ = client_and_session
    return tc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_novel(session, **kwargs) -> uuid.UUID:
    """Insert a Novel row and return its id."""
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
    """Insert a Task row and return its id."""
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


def test_list_scripts(client, db_engine):
    """GET /api/scripts/ — list scripts with filters and scene_count."""
    # Create test data via a clean session
    session = _session_factory()
    try:
        nid = _make_novel(session, title="List Test Novel")
        tid = _make_task(
            session,
            nid,
            script_json={
                "scenes": [{"id": 1}, {"id": 2}, {"id": 3}],
            },
        )
        session.commit()
    finally:
        session.close()

    # List all scripts
    resp = client.get("/api/v1/scripts/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["total"] >= 1
    items = body["data"]["items"]
    script_ids = [i["script_id"] for i in items]
    assert str(tid) in script_ids

    # Verify scene_count for our task
    our = next(i for i in items if i["script_id"] == str(tid))
    assert our["scene_count"] == 3

    # Filter by novel_id
    resp2 = client.get(f"/api/v1/scripts/?novel_id={nid}")
    assert resp2.status_code == 200
    items2 = resp2.json()["data"]["items"]
    assert all(i["novel_id"] == str(nid) for i in items2)

    # Filter by status
    resp3 = client.get("/api/v1/scripts/?status=completed")
    assert resp3.status_code == 200
    items3 = resp3.json()["data"]["items"]
    assert all(i["status"] == "completed" for i in items3)

    # Pagination
    resp4 = client.get("/api/v1/scripts/?page=1&limit=1")
    assert resp4.status_code == 200
    assert resp4.json()["data"]["limit"] == 1
    assert resp4.json()["data"]["page"] == 1

    # Cleanup
    _cleanup_session(session, nid, tid)


def test_get_script(client, db_engine):
    """GET /api/scripts/{task_id} — return full script data."""
    session = _session_factory()
    try:
        nid = _make_novel(session, title="Get Test Novel")
        tid = _make_task(
            session,
            nid,
            script_yaml="scenes:\n  - id: 1\n    heading: Opening",
            script_json={"scenes": [{"id": 1, "heading": "Opening"}]},
            script_fountain="INT. ROOM - DAY\n\nHello world!",
            characters_json={"hero": {"name": "John", "age": 30}},
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/v1/scripts/{tid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["script_id"] == str(tid)
    assert data["novel_id"] == str(nid)
    assert data["status"] == "completed"
    assert data["script_yaml"] == "scenes:\n  - id: 1\n    heading: Opening"
    assert data["script_json"] == {"scenes": [{"id": 1, "heading": "Opening"}]}
    assert data["script_fountain"] == "INT. ROOM - DAY\n\nHello world!"
    assert data["characters_json"] == {"hero": {"name": "John", "age": 30}}

    # 404 for nonexistent task
    resp404 = client.get(f"/api/v1/scripts/{uuid.uuid4()}")
    assert resp404.status_code == 404

    # Cleanup
    _cleanup_session(session, nid, tid)


def test_put_valid_yaml(client_and_session, db_engine):
    """PUT /api/scripts/{task_id} — update with valid YAML, create Operation."""
    tc, test_session = client_and_session
    # Create test data via the shared session so the API can see it
    nid = _make_novel(test_session, title="Put Valid Test")
    tid = _make_task(
        test_session,
        nid,
        script_yaml="original: value",
    )
    test_session.commit()

    valid_yaml = "scenes:\n  - id: 1\n    heading: Updated Scene\n    dialogue:\n      - character: ALICE\n        line: Hello"
    resp = tc.put(
        f"/api/v1/scripts/{tid}",
        json={"script_yaml": valid_yaml},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["script_id"] == str(tid)
    assert data["updated_at"] is not None
    assert data["validation"]["valid"] is True
    assert data["validation"]["errors"] is None

    # Verify the YAML was actually saved (read via API — same session)
    resp_get = tc.get(f"/api/v1/scripts/{tid}")
    assert resp_get.status_code == 200
    assert resp_get.json()["data"]["script_yaml"] == valid_yaml

    # Verify Operation record was created — query within the SAME transaction
    from app.models.sql import Operation

    test_session.commit()  # flush the API's uncommitted writes so query sees them
    ops = test_session.query(Operation).filter(Operation.task_id == tid).all()
    assert len(ops) >= 1
    assert ops[-1].type == "manual_edit"
    assert ops[-1].target_path == "/script_yaml"

    # Cleanup
    _cleanup_session(test_session, nid, tid)


def test_put_invalid_yaml_422(client, db_engine):
    """PUT /api/scripts/{task_id} — invalid YAML returns 422."""
    session = _session_factory()
    try:
        nid = _make_novel(session, title="Put Invalid Test")
        tid = _make_task(session, nid)
        session.commit()
    finally:
        session.close()

    # Malformed YAML (tab character is illegal)
    invalid_yaml = "scenes:\n\t- id: 1"
    resp = client.put(
        f"/api/v1/scripts/{tid}",
        json={"script_yaml": invalid_yaml},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "Invalid YAML" in body.get("message", "")

    # Cleanup
    _cleanup_session(session, nid, tid)


def test_export(client, db_engine):
    """GET /api/scripts/{task_id}/export — raw text in yaml/json/fountain."""
    session = _session_factory()
    try:
        nid = _make_novel(session, title="Export Test")
        sample_yaml = "scenes:\n  - id: 1\n    heading: Export Test"
        sample_json = {"scenes": [{"id": 1, "heading": "Export Test"}]}
        sample_fountain = "INT. OFFICE - DAY\n\nTesting export."
        tid = _make_task(
            session,
            nid,
            script_yaml=sample_yaml,
            script_json=sample_json,
            script_fountain=sample_fountain,
        )
        session.commit()
    finally:
        session.close()

    # Export YAML
    resp_yaml = client.get(f"/api/v1/scripts/{tid}/export?format=yaml")
    assert resp_yaml.status_code == 200
    assert resp_yaml.text == sample_yaml

    # Export JSON
    resp_json = client.get(f"/api/v1/scripts/{tid}/export?format=json")
    assert resp_json.status_code == 200
    parsed = json.loads(resp_json.text)
    assert parsed == sample_json

    # Export Fountain
    resp_fountain = client.get(f"/api/v1/scripts/{tid}/export?format=fountain")
    assert resp_fountain.status_code == 200
    assert resp_fountain.text == sample_fountain

    # 404 for nonexistent task
    resp404 = client.get(f"/api/v1/scripts/{uuid.uuid4()}/export?format=yaml")
    assert resp404.status_code == 404

    # 422 for unsupported format — FastAPI validates the pattern so we get
    # a standard 422 from request validation, not from our code.
    resp_bad = client.get(f"/api/v1/scripts/{tid}/export?format=invalid")
    assert resp_bad.status_code == 422

    # Cleanup
    _cleanup_session(session, nid, tid)


# ---------------------------------------------------------------------------
# Cleanup helper (runs in a fresh session so the API session is untouched)
# ---------------------------------------------------------------------------


def _cleanup_session(original_session, nid, tid):
    """Delete test data using original_session (still open for rollback).

    This runs AFTER the test assertions, just before the fixture's
    rollback.  The data is already committed in the DB but will be
    cleaned up by a fresh operation.
    """
    from app.models.sql import Novel, Task

    s = _session_factory()
    try:
        # Delete task first (FK), then novel
        task = s.get(Task, tid)
        if task:
            s.delete(task)
        novel = s.get(Novel, nid)
        if novel:
            s.delete(novel)
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()
