"""Tests for Agent D: Novel Management API.

All tests are synchronous — no async/await.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.sql import Chapter as ChapterModel
from app.models.sql import Novel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    """TestClient whose get_db dependency is pointed at the rollback-session."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Upload — success
# ---------------------------------------------------------------------------


def test_upload_creates_novel_and_chapters(client, db, auth_headers):
    """Uploading text with Chinese chapter markers creates Novel + Chapters."""
    payload = {
        "content": "第一章 大梦初醒\n清晨的阳光洒在窗台上。\n第二章 远行\n马车缓缓驶出城门。\n第三章 相遇\n他在桥头遇见了她。",
        "title": "测试小说",
        "author": "测试作者",
    }
    resp = client.post("/api/v1/novels/upload", json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["title"] == "测试小说"
    assert "task_id" in data  # auto-create Task for conversion
    assert data["task_status"] == "pending"

    novel_id = data["novel_id"]
    # Verify in DB
    novel = db.get(Novel, novel_id)
    assert novel is not None
    assert novel.title == "测试小说"
    assert novel.author == "测试作者"
    assert novel.word_count > 0


# ---------------------------------------------------------------------------
# 2. Upload — empty content → 400
# ---------------------------------------------------------------------------


def test_upload_empty_400(client, auth_headers):
    """Empty or whitespace-only content should return HTTP 400."""
    resp = client.post("/api/v1/novels/upload", json={"content": ""}, headers=auth_headers)
    assert resp.status_code == 400, resp.text

    resp2 = client.post("/api/v1/novels/upload", json={"content": "   "}, headers=auth_headers)
    assert resp2.status_code == 400, resp2.text


# ---------------------------------------------------------------------------
# 3. List — paginated
# ---------------------------------------------------------------------------


def test_list_paginated(client, db):
    """GET / returns paginated novels with total count."""
    # Seed 5 novels
    for i in range(5):
        novel = Novel(
            title=f"Novel {i}",
            source_text=f"Content of novel {i}.",
        )
        db.add(novel)
    db.flush()

    # Page 1: limit 2
    resp = client.get("/api/v1/novels/?page=1&limit=2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["total"] >= 5
    assert len(body["data"]["items"]) == 2

    # Page 3: should have at least 1 item
    resp2 = client.get("/api/v1/novels/?page=3&limit=2")
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert len(body2["data"]["items"]) >= 1

    # No page param → defaults to page 1
    resp3 = client.get("/api/v1/novels/")
    assert resp3.status_code == 200, resp3.text


# ---------------------------------------------------------------------------
# 4. Detail — single novel with chapters
# ---------------------------------------------------------------------------


def test_get_single_novel(client, db):
    """GET /{novel_id} returns novel detail with nested chapters."""
    nid = uuid.uuid4()
    novel = Novel(
        id=nid,
        title="Detail Test Novel",
        author="Detail Author",
        source_text="Some source text.",
    )
    db.add(novel)
    db.flush()

    # Add 2 chapters
    for idx in range(2):
        ch = ChapterModel(
            novel_id=nid,
            chapter_index=idx,
            title=f"Chapter {idx}",
            content=f"Body of chapter {idx}.",
        )
        db.add(ch)
    db.flush()

    resp = client.get(f"/api/v1/novels/{nid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["novel"]["title"] == "Detail Test Novel"
    assert body["data"]["novel"]["author"] == "Detail Author"
    assert "chapters" in body["data"]
    assert len(body["data"]["chapters"]) == 2


# ---------------------------------------------------------------------------
# 5. Delete — cascade
# ---------------------------------------------------------------------------


def test_delete_cascades(client, db, auth_headers):
    """DELETE /{novel_id} removes the novel and all its chapters."""
    nid = uuid.uuid4()
    novel = Novel(
        id=nid,
        title="Delete Me",
        source_text="To be removed.",
    )
    db.add(novel)
    db.flush()

    # Add a chapter
    ch = ChapterModel(
        novel_id=nid,
        chapter_index=0,
        title="Ch One",
        content="Chapter content to be deleted.",
    )
    db.add(ch)
    db.flush()

    resp = client.delete(f"/api/v1/novels/{nid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["deleted_id"] == str(nid)

    # Novel is gone
    assert db.get(Novel, nid) is None

    # Chapters are gone
    from sqlmodel import select

    remaining = db.execute(
        select(ChapterModel).where(ChapterModel.novel_id == nid)
    ).scalars().all()
    assert len(remaining) == 0

    # Deleting again → 404
    resp2 = client.delete(f"/api/v1/novels/{nid}", headers=auth_headers)
    assert resp2.status_code == 404, resp2.text
