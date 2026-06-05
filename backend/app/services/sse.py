"""SSE progress streaming stub — logs progress events for now.

Future: integrate with sse-starlette ServerSentEvent for real-time streaming.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def push_progress(task_id: uuid.UUID | str, progress: int, stage: str) -> None:
    """Log a progress update for the given task.

    This is a stub that will be replaced with actual SSE emission once
    the pipeline execution engine is integrated.

    Args:
        task_id: UUID of the task.
        progress: Progress percentage (0-100).
        stage: Human-readable stage name (e.g. "chunking", "converting").
    """
    logger.info(
        "SSE push: task=%s progress=%s stage=%s",
        str(task_id),
        progress,
        stage,
    )
