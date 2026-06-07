"""Tests for Agent G — AI editor / chat API (v3: script-centric)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.redis import get_redis
from app.main import app
from app.models.sql import Dialogue, Novel, Operation, Script, Task


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def client(db, redis_client):
    def _override_get_db():
        return db
    def _override_get_redis():
        yield redis_client
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_llm():
    mock_msg = MagicMock()
    mock_msg.content = (
        "I suggest changing the opening scene title.\n\n"
        "```json\n"
        '{"op": "replace", "path": "/scenes/0/title", "value": "New Opening"}\n'
        "```"
    )
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = mock_msg
    with patch("app.api.v1.editor.get_llm", return_value=mock_llm_instance):
        yield


@pytest.fixture
def sample_script(db):
    """A Script + optional Task ready for editing."""
    novel = Novel(title="Test Novel", author="Test Author", source_text="Once upon a time...")
    db.add(novel)
    db.flush()

    script = Script(
        novel_id=novel.id,
        title="Test Script",
        source_type="generated",
        status="editing",
        summary="A test adaptation.",
        characters_json={"characters": [{"name": "Hero", "role": "protagonist"}]},
        script_yaml="scenes:\n  - id: scene_1\n    title: Original Title\n",
        script_json={
            "title": "Original Title",
            "scenes": [{"id": "scene_1", "title": "Original Title", "characters": ["Hero"]}],
        },
    )
    db.add(script)
    db.flush()

    task = Task(novel_id=novel.id, script_id=script.id, status="completed", progress=100)
    db.add(task)
    db.flush()
    return script


# ── Tests ───────────────────────────────────────────────────────────


def test_chat_saves_dialogue(client, sample_script, mock_llm, db, auth_headers):
    """POST /chat/{script_id} persists user + assistant Dialogue rows."""
    sid = str(sample_script.id)
    payload = {"message": "Can you improve the scene title?"}

    response = client.post(f"/api/v1/editor/chat/{sid}", json=payload, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "reply" in data["data"]
    assert data["data"]["patch"] is not None

    dialogues = (
        db.query(Dialogue)
        .filter(Dialogue.script_id == sample_script.id)
        .order_by(Dialogue.created_at.asc())
        .all()
    )
    assert len(dialogues) == 2
    assert dialogues[0].role == "user"
    assert dialogues[0].content == "Can you improve the scene title?"
    assert dialogues[1].role == "assistant"
    assert "New Opening" in dialogues[1].content
    assert dialogues[1].patch_json is not None
    assert dialogues[1].patch_json.get("op") == "replace"


def test_chat_script_not_found_404(client, mock_llm, auth_headers):
    """POST /chat/{script_id} returns 404 for a nonexistent script."""
    fake_id = str(uuid.uuid4())
    payload = {"message": "Hello"}
    response = client.post(f"/api/v1/editor/chat/{fake_id}", json=payload, headers=auth_headers)
    assert response.status_code == 404


def test_apply_patch_updates_script(client, sample_script, db, auth_headers):
    """POST /apply_patch/{script_id} applies a JSON Patch and records an Operation."""
    sid = str(sample_script.id)
    payload = {"op": "replace", "path": "/scenes/0/title", "value": "Updated Scene Title"}

    response = client.post(f"/api/v1/editor/apply_patch/{sid}", json=payload, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["script_json"]["scenes"][0]["title"] == "Updated Scene Title"

    ops = (
        db.query(Operation)
        .filter(Operation.script_id == sample_script.id)
        .order_by(Operation.created_at.desc())
        .all()
    )
    assert len(ops) == 1
    assert ops[0].type == "ai_patch"
    assert ops[0].target_path == "/scenes/0/title"
    assert ops[0].previous_snapshot is not None
    assert ops[0].previous_snapshot.get("/scenes/0/title") == "Original Title"

    db.refresh(sample_script)
    assert sample_script.script_json["scenes"][0]["title"] == "Updated Scene Title"


def test_undo_rolls_back(client, sample_script, db, auth_headers):
    """POST /undo/{script_id} reverses the most recent patch operation."""
    sid = str(sample_script.id)

    patch_payload = {"op": "replace", "path": "/title", "value": "Changed Title"}
    r1 = client.post(f"/api/v1/editor/apply_patch/{sid}", json=patch_payload, headers=auth_headers)
    assert r1.status_code == 200

    db.refresh(sample_script)
    assert sample_script.script_json["title"] == "Changed Title"

    r2 = client.post(f"/api/v1/editor/undo/{sid}", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["code"] == 200

    db.refresh(sample_script)
    assert sample_script.script_json["title"] == "Original Title"

    ops = (
        db.query(Operation)
        .filter(Operation.script_id == sample_script.id, Operation.type == "rollback")
        .all()
    )
    assert len(ops) == 1

    r3 = client.post(f"/api/v1/editor/undo/{sid}", headers=auth_headers)
    assert r3.status_code == 400


def test_chat_with_scene_injects_context(client, sample_script, mock_llm, db, auth_headers):
    """POST /chat/{script_id} with scene_id works."""
    sid = str(sample_script.id)
    payload = {"message": "Fix this scene", "scene_id": "scene_1"}

    response = client.post(f"/api/v1/editor/chat/{sid}", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert "reply" in response.json()["data"]

    dialogues = (
        db.query(Dialogue)
        .filter(Dialogue.script_id == sample_script.id)
        .order_by(Dialogue.created_at.asc())
        .all()
    )
    assert any(d.role == "user" and d.meta.get("scene_id") == "scene_1" for d in dialogues)
