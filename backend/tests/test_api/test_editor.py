"""Tests for Agent G — AI editor / chat API."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.sql import Dialogue, Novel, Operation, Task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    """TestClient wired to the test database session."""

    def _override_get_db():
        return db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_llm():
    """Replace ``get_llm`` with a mock that returns a canned AI response."""
    mock_msg = MagicMock()
    mock_msg.content = (
        "I suggest changing the opening scene title.\n\n"
        "```json\n"
        '{"op": "replace", "path": "/scenes/0/title", "value": "New Opening"}\n'
        "```"
    )

    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.return_value = mock_msg

    with patch("app.api.editor.get_llm", return_value=mock_llm_instance):
        yield


@pytest.fixture
def sample_task(db):
    """A completed Task with script_json ready for editing."""
    novel = Novel(
        title="Test Novel",
        author="Test Author",
        source_text="Once upon a time...",
    )
    db.add(novel)
    db.flush()

    task = Task(
        novel_id=novel.id,
        status="completed",
        progress=100,
        summary="A test adaptation.",
        characters_json={
            "characters": [{"name": "Hero", "role": "protagonist"}]
        },
        script_yaml="scenes:\n  - id: scene_1\n    title: Original Title\n",
        script_json={
            "title": "Original Title",
            "scenes": [
                {
                    "id": "scene_1",
                    "title": "Original Title",
                    "characters": ["Hero"],
                }
            ],
        },
    )
    db.add(task)
    db.flush()
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chat_saves_dialogue(client, sample_task, mock_llm, db):
    """POST /chat/{task_id} persists user + assistant Dialogue rows."""
    task_id = str(sample_task.id)
    payload = {"message": "Can you improve the scene title?"}

    response = client.post(f"/api/v1/editor/chat/{task_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "reply" in data["data"]
    assert data["data"]["patch"] is not None

    # Verify two dialogue rows were created in the same session
    dialogues = (
        db.query(Dialogue)
        .filter(Dialogue.task_id == sample_task.id)
        .order_by(Dialogue.created_at.asc())
        .all()
    )
    assert len(dialogues) == 2
    assert dialogues[0].role == "user"
    assert dialogues[0].content == "Can you improve the scene title?"
    assert dialogues[1].role == "assistant"
    assert "New Opening" in dialogues[1].content

    # Assistant dialogue should have the extracted patch
    assert dialogues[1].patch_json is not None
    assert dialogues[1].patch_json.get("op") == "replace"


def test_chat_task_not_found_404(client, mock_llm):
    """POST /chat/{task_id} returns 404 for a nonexistent task."""
    fake_id = str(uuid.uuid4())
    payload = {"message": "Hello"}

    response = client.post(f"/api/v1/editor/chat/{fake_id}", json=payload)

    assert response.status_code == 404


def test_apply_patch_updates_script(client, sample_task, db):
    """POST /apply_patch/{task_id} applies a JSON Patch and records an Operation."""
    task_id = str(sample_task.id)
    payload = {
        "op": "replace",
        "path": "/scenes/0/title",
        "value": "Updated Scene Title",
    }

    response = client.post(f"/api/v1/editor/apply_patch/{task_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["data"]["script_json"]["scenes"][0]["title"] == "Updated Scene Title"

    # Verify Operation row
    ops = (
        db.query(Operation)
        .filter(Operation.task_id == sample_task.id)
        .order_by(Operation.created_at.desc())
        .all()
    )
    assert len(ops) == 1
    assert ops[0].type == "ai_patch"
    assert ops[0].target_path == "/scenes/0/title"
    # previous_snapshot should hold the old title
    assert ops[0].previous_snapshot is not None
    assert ops[0].previous_snapshot.get("/scenes/0/title") == "Original Title"

    # Re-fetch task to confirm persistence
    db.refresh(sample_task)
    assert sample_task.script_json["scenes"][0]["title"] == "Updated Scene Title"


def test_undo_rolls_back(client, sample_task, db):
    """POST /undo/{task_id} reverses the most recent patch operation."""
    task_id = str(sample_task.id)

    # First, apply a patch
    patch_payload = {
        "op": "replace",
        "path": "/title",
        "value": "Changed Title",
    }
    r1 = client.post(f"/api/v1/editor/apply_patch/{task_id}", json=patch_payload)
    assert r1.status_code == 200

    # Verify the patch was applied
    db.refresh(sample_task)
    assert sample_task.script_json["title"] == "Changed Title"

    # Now undo
    r2 = client.post(f"/api/v1/editor/undo/{task_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["code"] == 200

    # Verify the title was rolled back
    db.refresh(sample_task)
    assert sample_task.script_json["title"] == "Original Title"

    # Verify a rollback Operation was recorded
    ops = (
        db.query(Operation)
        .filter(
            Operation.task_id == sample_task.id,
            Operation.type == "rollback",
        )
        .all()
    )
    assert len(ops) == 1

    # Undo with no more operations should return 400
    r3 = client.post(f"/api/v1/editor/undo/{task_id}")
    assert r3.status_code == 400


def test_chat_with_scene_injects_context(client, sample_task, mock_llm, db):
    """POST /chat/{task_id} with scene_id includes scene context in the prompt."""
    task_id = str(sample_task.id)
    payload = {
        "message": "Fix this scene",
        "scene_id": "scene_1",
    }

    response = client.post(f"/api/v1/editor/chat/{task_id}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "reply" in data["data"]

    # The dialogue meta should include the scene_id
    dialogues = (
        db.query(Dialogue)
        .filter(
            Dialogue.task_id == sample_task.id,
            Dialogue.role == "user",
        )
        .all()
    )
    assert len(dialogues) == 1
    assert dialogues[0].meta.get("scene_id") == "scene_1"
