"""Tests for ProgressManager — now a no-op Celery compatibility stub."""

from __future__ import annotations

import uuid

from app.services.progress import progress_manager


class TestProgressManagerNoOp:
    """All methods are no-ops — must not raise (backward-compat)."""

    def test_create_and_remove(self) -> None:
        q = progress_manager.create_queue("task-1")
        assert q is None
        progress_manager.remove_queue("task-1")
        progress_manager.cleanup("task-1")

    def test_push_methods_silently_succeed(self) -> None:
        progress_manager.push("task-1", "progress", {"pct": 50})
        progress_manager.push_progress("task-1", 30, "chunking")
        progress_manager.push_error("task-1", "boom")
        progress_manager.push_complete("task-1")
        progress_manager.push(uuid.uuid4(), "x", {})

    def test_get_nowait_always_returns_none(self) -> None:
        progress_manager.create_queue("task-1")
        assert progress_manager.get_nowait("task-1") is None
        assert progress_manager.get_nowait("ghost") is None

    def test_cleanup_idempotent(self) -> None:
        progress_manager.cleanup("nope")
        progress_manager.cleanup("nope")
