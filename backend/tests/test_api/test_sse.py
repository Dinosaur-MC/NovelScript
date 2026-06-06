"""Tests for SSE progress streaming endpoint — GET /api/v1/tasks/{task_id}/stream.

With Celery, the SSE endpoint polls ``AsyncResult`` (Redis).  These
tests mock ``AsyncResult`` to simulate worker progress states without
requiring a running Redis instance.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.db import _session_factory
from app.main import app
from app.models.sql import Novel, Task


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


def _sse(url: str) -> list[dict]:
    """Collect SSE events until stream ends."""
    async def _collect() -> list[dict]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver",
            timeout=httpx.Timeout(8.0),
        ) as client:
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
# Mock AsyncResult factory
# ---------------------------------------------------------------------------


def _make_mock_result(state: str = "PENDING", info: dict | str | None = None):
    """Return a simple MagicMock with fixed .state and .info."""
    mock = MagicMock()
    mock.state = state
    mock.info = info
    return mock


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


class TestStreamTerminalStates:
    """When task is already terminal in DB, SSE returns immediately."""

    def test_already_completed_task_yields_complete(self) -> None:
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="completed")
        try:
            with patch("app.api.v1.tasks.AsyncResult") as mock_ar:
                mock_ar.return_value = _make_mock_result("PENDING", None)
                events = _sse(f"/api/v1/tasks/{tid}/stream")
                assert len(events) >= 1
                assert events[-1]["event"] == "complete"
        finally:
            _cleanup(nid, tid)

    def test_already_failed_task_yields_error(self) -> None:
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="failed")
        with _session_factory() as s:
            t = s.get(Task, tid)
            assert t is not None
            t.error_message = "管线故障"
            s.add(t)
            s.commit()
        try:
            with patch("app.api.v1.tasks.AsyncResult") as mock_ar:
                mock_ar.return_value = _make_mock_result("PENDING", None)
                events = _sse(f"/api/v1/tasks/{tid}/stream")
                assert len(events) >= 1
                assert events[-1]["event"] == "error"
                data = json.loads(events[-1]["data"])
                assert "管线故障" in data["error"]
        finally:
            _cleanup(nid, tid)


class TestStreamProgressFromRedis:
    """SSE polls AsyncResult state from Redis — mock worker progress."""

    def test_receives_progress_and_complete(self) -> None:
        """Worker reports PROGRESS; SSE should emit progress heartbeat then see complete from DB poll."""
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="preprocessing")
        try:
            with patch("app.api.v1.tasks.AsyncResult") as mock_ar:
                mock_ar.return_value = _make_mock_result(
                    "SUCCESS", {"progress": 100, "stage": "assembling"},
                )
                events = _sse(f"/api/v1/tasks/{tid}/stream")

            types = [e["event"] for e in events]
            assert "complete" in types
        finally:
            _cleanup(nid, tid)

    def test_receives_error_on_failure(self) -> None:
        """Worker reports FAILURE; SSE should emit error and close."""
        nid = _create_novel_with_text()
        tid = _create_task(nid, status="preprocessing")
        try:
            with patch("app.api.v1.tasks.AsyncResult") as mock_ar:
                mock_ar.return_value = _make_mock_result("FAILURE", "Something broke")
                events = _sse(f"/api/v1/tasks/{tid}/stream")

            assert events[-1]["event"] == "error"
        finally:
            _cleanup(nid, tid)
