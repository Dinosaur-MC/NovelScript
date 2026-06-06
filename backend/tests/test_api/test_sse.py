"""Tests for SSE progress streaming endpoint — GET /api/v1/tasks/{task_id}/stream.

Uses ``httpx.AsyncClient`` with the ASGI transport so async streaming
endpoints work correctly.  Each test calls ``asyncio.run()`` — no
``pytest-asyncio`` needed.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from app.core.db import _session_factory
from app.main import app
from app.models.sql import Novel, Task
from app.services.progress import progress_manager


@pytest.fixture(autouse=True)
def _clean_progress():
    yield
    with progress_manager._lock:
        progress_manager._queues.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_novel_with_text(source_text: str = "第一章 测试\n内容。") -> uuid.UUID:
    nid = uuid.uuid4()
    with _session_factory() as s:
        novel = Novel(id=nid, title="SSE Test", source_text=source_text)
        s.add(novel)
        s.commit()
    return nid


def _create_task(novel_id: uuid.UUID, status: str = "pending") -> uuid.UUID:
    tid = uuid.uuid4()
    with _session_factory() as s:
        task = Task(id=tid, novel_id=novel_id, status=status, progress=0)
        s.add(task)
        s.commit()
    return tid


def _cleanup(nid: uuid.UUID, tid: uuid.UUID) -> None:
    with _session_factory() as s:
        t = s.get(Task, tid)
        if t:
            s.delete(t)
        n = s.get(Novel, nid)
        if n:
            s.delete(n)
        s.commit()


def _sse(url: str, timeout: float = 5.0) -> list[dict]:
    """Connect to *url*, collect SSE events until stream ends or timeout.

    Returns a list of ``{"event": str, "data": str}`` dicts.
    The stream MUST terminate on its own (via complete/error event);
    otherwise the function will block until *timeout*.
    """
    async def _collect() -> list[dict]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                      timeout=httpx.Timeout(timeout)) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                events: list[dict] = []
                async for line in resp.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = line[6:]
                        events.append({"event": event_type, "data": data})
                        if event_type in ("complete", "error"):
                            break
                return events

    return asyncio.run(_collect())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamErrors:
    def test_bad_uuid_returns_400(self) -> None:
        async def _go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                resp = await c.get("/api/v1/tasks/not-a-uuid/stream")
                return resp.status_code
        assert asyncio.run(_go()) == 400

    def test_nonexistent_task_returns_404(self) -> None:
        fake_id = uuid.uuid4()
        async def _go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                resp = await c.get(f"/api/v1/tasks/{fake_id}/stream")
                return resp.status_code
        assert asyncio.run(_go()) == 404


class TestStreamEvents:
    def test_receives_progress_events(self) -> None:
        """Pre-populate queue; then connect and verify events are received."""
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="preprocessing")
        try:
            q = progress_manager.create_queue(str(tid))
            progress_manager.push_progress(tid, 10, "chunking")
            progress_manager.push_progress(tid, 50, "converting")
            progress_manager.push_complete(tid)

            events = _sse(f"/api/v1/tasks/{tid}/stream")
            types = [e["event"] for e in events]
            assert "progress" in types
            assert "complete" in types
            # Verify at least one progress event has our data
            progress_events = [e for e in events if e["event"] == "progress"]
            assert any("chunking" in e["data"] for e in progress_events)
        finally:
            _cleanup(nid, tid)

    def test_already_completed_task_yields_complete(self) -> None:
        """When task is completed, stream yields single complete event."""
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="completed")
        try:
            events = _sse(f"/api/v1/tasks/{tid}/stream")
            assert len(events) >= 1
            assert events[-1]["event"] == "complete"
        finally:
            _cleanup(nid, tid)

    def test_already_failed_task_yields_error(self) -> None:
        """When task is failed, stream yields error event."""
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="failed")
        with _session_factory() as s:
            t = s.get(Task, tid)
            assert t is not None
            t.error_message = "管线故障"
            s.add(t)
            s.commit()
        try:
            events = _sse(f"/api/v1/tasks/{tid}/stream")
            assert len(events) >= 1
            assert events[-1]["event"] == "error"
            # Data is JSON-encoded, may contain unicode escapes
            data = json.loads(events[-1]["data"])
            assert "管线故障" in data["error"]
        finally:
            _cleanup(nid, tid)
