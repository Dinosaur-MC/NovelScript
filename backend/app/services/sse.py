"""SSE progress streaming — delegates to the ProgressManager singleton.

All pipeline callers import ``push_progress`` from this module so the
implementation can be swapped without touching the CLI or executor.
"""

from __future__ import annotations

import logging
import uuid

from app.services.progress import progress_manager

logger = logging.getLogger(__name__)


def push_progress(task_id: uuid.UUID | str, progress: int, stage: str) -> None:
    """Push a progress event through the ProgressManager singleton.

    If no SSE client is connected for *task_id* the event is silently
    dropped (the ProgressManager queue is created lazily).

    Args:
        task_id: UUID of the task.
        progress: Progress percentage (0-100).
        stage: Human-readable stage name (e.g. "chunking", "converting").
    """
    progress_manager.push_progress(task_id, progress, stage)
    logger.debug(
        "SSE push: task=%s progress=%s stage=%s",
        str(task_id),
        progress,
        stage,
    )
