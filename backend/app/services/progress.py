"""ProgressManager — thread-safe singleton for SSE progress event distribution.

A single ``ProgressManager`` instance lives for the application lifetime.
Background pipeline-executor threads **push** events; async SSE endpoint
generators **poll** them via ``get_nowait()``.

Design
------
- ``queue.Queue`` (stdlib) is inherently thread-safe — no need for
  ``loop.call_soon_threadsafe`` or other asyncio bridging.
- Each task gets its own queue, created lazily when the first SSE client
  connects.  If no client ever connects, events are silently dropped.
- A ``_sentinel`` sentinel signals the generator to exit cleanly.
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_SENTINEL = object()


class ProgressManager:
    """Thread-safe singleton that routes pipeline progress → SSE queues."""

    def __init__(self) -> None:
        self._queues: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Queue lifecycle
    # ------------------------------------------------------------------

    def create_queue(self, task_id: str) -> queue.Queue:
        """Return the queue for *task_id*, creating it if needed.

        Idempotent — multiple calls return the same queue.
        """
        with self._lock:
            q = self._queues.get(task_id)
            if q is None:
                q = queue.Queue()
                self._queues[task_id] = q
            return q

    def remove_queue(self, task_id: str) -> None:
        """Remove and return the queue for *task_id* (or None)."""
        with self._lock:
            return self._queues.pop(task_id, None)

    # ------------------------------------------------------------------
    # Pushing events (called from background threads)
    # ------------------------------------------------------------------

    def push(self, task_id: str | uuid.UUID, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Push an event dict onto the queue for *task_id*.

        Thread-safe fire-and-forget.  If no queue has been created for
        *task_id* the event is silently dropped (no SSE client connected).
        """
        tid = str(task_id)
        with self._lock:
            q = self._queues.get(tid)
        if q is None:
            return
        try:
            q.put_nowait({"type": event_type, "data": data or {}})
        except queue.Full:
            logger.debug("Queue full for task %s — dropping event.", tid)

    def push_progress(self, task_id: str | uuid.UUID, progress: int, stage: str) -> None:
        """Push a ``progress`` event (percentage + human-readable stage)."""
        self.push(task_id, "progress", {"progress": progress, "stage": stage})

    def push_error(self, task_id: str | uuid.UUID, error_message: str) -> None:
        """Push an ``error`` event that signals the stream should close."""
        self.push(task_id, "error", {"error": error_message})

    def push_complete(self, task_id: str | uuid.UUID) -> None:
        """Push a ``complete`` event that signals the stream should close."""
        self.push(task_id, "complete", {"progress": 100})

    # ------------------------------------------------------------------
    # Generator helpers (called from async SSE endpoints)
    # ------------------------------------------------------------------

    def get_nowait(self, task_id: str) -> dict[str, Any] | None:
        """Non-blocking poll — return next event or None."""
        with self._lock:
            q = self._queues.get(task_id)
        if q is None:
            return None
        try:
            return q.get_nowait()
        except queue.Empty:
            return None

    def cleanup(self, task_id: str) -> None:
        """Drop the queue so background pushes become no-ops.

        Safe to call multiple times.
        """
        self.remove_queue(task_id)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

progress_manager = ProgressManager()
