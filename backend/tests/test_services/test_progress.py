"""Tests for ProgressManager — thread-safe singleton (no DB needed)."""

from __future__ import annotations

import queue
import threading

import pytest

from app.services.progress import progress_manager


@pytest.fixture(autouse=True)
def _clean_queues():
    """Remove any leftover queues between tests."""
    yield
    # Drop all queues that may have been created during the test
    # (ProgressManager can't enumerate them, so we use a fresh instance property)
    with progress_manager._lock:
        progress_manager._queues.clear()


class TestCreateQueue:
    def test_create_returns_a_queue(self) -> None:
        q = progress_manager.create_queue("task-1")
        assert isinstance(q, queue.Queue)

    def test_create_is_idempotent(self) -> None:
        q1 = progress_manager.create_queue("task-1")
        q2 = progress_manager.create_queue("task-1")
        assert q1 is q2

    def test_different_tasks_get_different_queues(self) -> None:
        q1 = progress_manager.create_queue("task-1")
        q2 = progress_manager.create_queue("task-2")
        assert q1 is not q2


class TestPush:
    def test_push_puts_event_on_queue(self) -> None:
        q = progress_manager.create_queue("task-1")
        progress_manager.push("task-1", "progress", {"pct": 50})
        event = q.get_nowait()
        assert event["type"] == "progress"
        assert event["data"] == {"pct": 50}

    def test_push_nonexistent_queue_is_noop(self) -> None:
        # This must not raise
        progress_manager.push("no-such-task", "progress", {"pct": 99})

    def test_push_progress_convenience(self) -> None:
        q = progress_manager.create_queue("task-1")
        progress_manager.push_progress("task-1", 30, "chunking")
        event = q.get_nowait()
        assert event["type"] == "progress"
        assert event["data"] == {"progress": 30, "stage": "chunking"}

    def test_push_error_convenience(self) -> None:
        q = progress_manager.create_queue("task-1")
        progress_manager.push_error("task-1", "something broke")
        event = q.get_nowait()
        assert event["type"] == "error"
        assert event["data"]["error"] == "something broke"

    def test_push_complete_convenience(self) -> None:
        q = progress_manager.create_queue("task-1")
        progress_manager.push_complete("task-1")
        event = q.get_nowait()
        assert event["type"] == "complete"
        assert event["data"]["progress"] == 100


class TestGetNowait:
    def test_returns_none_when_queue_empty(self) -> None:
        progress_manager.create_queue("task-1")
        assert progress_manager.get_nowait("task-1") is None

    def test_returns_none_when_queue_absent(self) -> None:
        assert progress_manager.get_nowait("ghost") is None

    def test_returns_pushed_event(self) -> None:
        progress_manager.create_queue("task-1")
        progress_manager.push("task-1", "test", {"k": "v"})
        event = progress_manager.get_nowait("task-1")
        assert event is not None
        assert event["type"] == "test"


class TestCleanup:
    def test_remove_queue(self) -> None:
        progress_manager.create_queue("task-1")
        progress_manager.remove_queue("task-1")
        assert progress_manager.get_nowait("task-1") is None

    def test_cleanup_called_twice_is_safe(self) -> None:
        progress_manager.create_queue("task-1")
        progress_manager.cleanup("task-1")
        progress_manager.cleanup("task-1")  # must not raise


class TestThreadSafety:
    def test_concurrent_pushes(self) -> None:
        """Multiple threads pushing events simultaneously — no data loss."""
        q = progress_manager.create_queue("task-1")
        n_events = 200
        barrier = threading.Barrier(4)

        def _pusher(start: int) -> None:
            barrier.wait()  # synchronise start
            for i in range(start, start + 50):
                progress_manager.push("task-1", "tick", {"i": i})

        threads = [threading.Thread(target=_pusher, args=(i,)) for i in range(0, n_events, 50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Drain the queue
        count = 0
        while True:
            try:
                q.get_nowait()
                count += 1
            except queue.Empty:
                break
        assert count == n_events, f"Expected {n_events} events, got {count}"

    def test_push_and_poll_across_threads(self) -> None:
        """Background thread pushes; main thread polls."""
        q = progress_manager.create_queue("task-1")
        received: list[dict] = []

        def _bg():
            progress_manager.push_progress("task-1", 10, "a")
            progress_manager.push_progress("task-1", 50, "b")
            progress_manager.push_complete("task-1")

        bg = threading.Thread(target=_bg)
        bg.start()
        bg.join()

        while True:
            ev = progress_manager.get_nowait("task-1")
            if ev is None:
                break
            received.append(ev)

        assert len(received) == 3
        assert received[0]["type"] == "progress"
        assert received[2]["type"] == "complete"
