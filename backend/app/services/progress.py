"""ProgressManager — no-op compatibility shim.

With Celery, progress is reported via ``self.update_state()`` (Redis)
and read back via ``AsyncResult(task_id).info`` from the SSE endpoint.
No in-process queue is needed.  This module is retained as a stub so
existing import sites don't break during the migration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ProgressManager:
    """No-op singleton — all progress flows through Celery / Redis now."""

    # Backward-compatible stubs — callers that still import this won't crash
    def create_queue(self, task_id: str) -> None:
        pass

    def remove_queue(self, task_id: str) -> None:
        pass

    def push(self, task_id: str | uuid.UUID, event_type: str, data: dict[str, Any] | None = None) -> None:
        pass

    def push_progress(self, task_id: str | uuid.UUID, progress: int, stage: str) -> None:
        pass

    def push_error(self, task_id: str | uuid.UUID, error_message: str) -> None:
        pass

    def push_complete(self, task_id: str | uuid.UUID) -> None:
        pass

    def get_nowait(self, task_id: str) -> dict[str, Any] | None:
        return None

    def cleanup(self, task_id: str) -> None:
        pass


# Module-level singleton — backward-compatible
progress_manager = ProgressManager()
