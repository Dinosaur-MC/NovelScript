"""Pipeline executor — runs the pipeline in a background daemon thread.

When ``POST /api/v1/tasks/`` creates a task, the route handler calls
``execute_pipeline(task_id, novel_id)`` which spawns a daemon thread.
The thread manages its own DB session, reports progress through the
``ProgressManager`` singleton, and persists results to the Task row.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
import uuid
from datetime import datetime, timezone

from app.core.db import _session_factory
from app.models.sql import Chapter as ChapterModel, Novel, Task
from app.services.progress import progress_manager
from cli.exporter import to_json, to_yaml
from cli.models import Chapter
from cli.pipeline import ProgressCallback, run_from_chapters, run_from_text

logger = logging.getLogger(__name__)


def execute_pipeline(task_id: uuid.UUID, novel_id: uuid.UUID) -> None:
    """Spawn a daemon thread that runs the full pipeline for *task_id*.

    The thread:
    1. Opens its own synchronous DB session.
    2. Loads ``Novel.source_text`` — if empty, logs a warning and exits
       leaving the task ``pending``.
    3. Transitions the task through the status state machine, persisting
       progress and results after each major stage.
    4. Calls ``asyncio.run(run_from_text(...))`` with a progress callback
       that pushes SSE events via the ``ProgressManager``.
    5. On success: saves ``script_yaml``, ``script_json``, ``summary``,
       ``characters_json``, sets ``completed``, pushes SSE ``complete``.
    6. On failure: sets ``failed`` with ``error_message``, pushes SSE
       ``error``.

    This function returns immediately — do not await it.
    """
    thread = threading.Thread(
        target=_run_in_thread,
        args=(task_id, novel_id),
        name=f"pipeline-{task_id}",
        daemon=True,
    )
    thread.start()
    logger.info("Pipeline thread %s started for task %s.", thread.name, task_id)


# ---------------------------------------------------------------------------
# Internal — runs inside the background thread
# ---------------------------------------------------------------------------


def _run_in_thread(task_id: uuid.UUID, novel_id: uuid.UUID) -> None:
    session = _session_factory()
    tid = str(task_id)
    try:
        # ---- load novel -------------------------------------------------
        novel = session.get(Novel, novel_id)
        if novel is None:
            _fail(session, task_id, f"Novel {novel_id} not found.")
            return

        source = (novel.source_text or "").strip()
        if not source:
            logger.warning(
                "Novel %s has no source_text — leaving task %s pending.",
                novel_id, task_id,
            )
            return  # task stays "pending"

        # ---- progress callback (closure over session + task_id) ---------
        def _on_progress(progress: int, stage: str) -> None:
            """Called by pipeline stages — updates DB + pushes SSE."""
            try:
                task = session.get(Task, task_id)
                if task is None:
                    return

                task.progress = progress

                # Map stage → status via the state machine
                if stage in ("starting", "chunking", "summarizing", "graphrag", "rag"):
                    if task.status == "pending":
                        task.status = "preprocessing"
                elif stage in ("converting",):
                    if task.status in ("pending", "preprocessing"):
                        task.status = "converting"

                task.updated_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()

                progress_manager.push_progress(task_id, progress, stage)
            except Exception:
                logger.exception("Progress callback failed (ignored).")
                session.rollback()

        # ---- run pipeline ------------------------------------------------
        # Prefer DB-stored chapters (already split during upload) to avoid
        # re-running the LLM chunker on source_text.  Fall back to raw text
        # when no chapters exist in the database.
        chapters = _load_chapters(session, novel_id)
        if chapters:
            script = asyncio.run(
                run_from_chapters(
                    chapters,
                    progress_callback=_on_progress,
                    source_name=novel.title or str(novel_id),
                )
            )
        else:
            script = asyncio.run(
                run_from_text(
                    source,
                    progress_callback=_on_progress,
                    source_name=novel.title or str(novel_id),
                )
            )

        # ---- persist results ---------------------------------------------
        task = session.get(Task, task_id)
        if task is None:
            logger.error("Task %s disappeared during pipeline run.", task_id)
            return

        task.status = "completed"
        task.progress = 100
        task.summary = script.summary
        task.script_yaml = to_yaml(script)
        task.script_json = script.model_dump(mode="json")  # type: ignore[assignment]
        task.characters_json = [
            {"id": c.id, "name": c.name, "aliases": c.aliases, "properties": c.properties}
            for c in script.characters
        ]  # type: ignore[assignment]
        task.updated_at = datetime.now(timezone.utc)
        session.add(task)
        session.commit()

        progress_manager.push_complete(task_id)
        logger.info("Pipeline completed for task %s: %d scenes.", task_id, len(script.scenes))

    except Exception:
        logger.exception("Pipeline failed for task %s.", task_id)
        msg = traceback.format_exc()
        _fail(session, task_id, msg)
        progress_manager.push_error(task_id, msg)
    finally:
        session.close()
        progress_manager.cleanup(tid)


def _load_chapters(session, novel_id: uuid.UUID) -> list[Chapter] | None:
    """Load DB-stored chapters for *novel_id* as pipeline Chapter objects.

    Returns ``None`` when no chapters exist (caller falls back to raw text).
    """
    rows = (
        session.query(ChapterModel)
        .filter(ChapterModel.novel_id == novel_id)
        .order_by(ChapterModel.chapter_index.asc())
        .all()
    )
    if not rows:
        return None

    return [
        Chapter(text=r.content or "", title=r.title or f"第{i+1}章", index=r.chapter_index)
        for i, r in enumerate(rows)
    ]


def _fail(session, task_id: uuid.UUID, message: str) -> None:
    """Set *task_id* to ``failed`` with *message*."""
    try:
        task = session.get(Task, task_id)
        if task is not None:
            task.status = "failed"
            task.error_message = message[:5000]  # guard against huge tracebacks
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
    except Exception:
        logger.exception("Failed to persist failure for task %s.", task_id)
        session.rollback()


def recover_stale_tasks() -> int:
    """Mark in-flight tasks as ``failed`` after a server restart.

    Daemon threads are killed on server shutdown, so any task left in
    ``preprocessing`` or ``converting`` is orphaned.  This function
    moves them to ``failed`` with a descriptive error so users can
    resume them manually.

    Returns the number of tasks recovered.
    """
    session = _session_factory()
    try:
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        stale_msg = "Server restarted — pipeline interrupted. Use /resume to retry."
        result = session.execute(
            update(Task)
            .where(Task.status.in_(["preprocessing", "converting"]))
            .values(status="failed", error_message=stale_msg, updated_at=now)
        )
        session.commit()
        count = result.rowcount
        if count:
            logger.warning("Recovered %d stale task(s) after server restart.", count)
        return count
    except Exception:
        session.rollback()
        logger.exception("Failed to recover stale tasks.")
        return 0
    finally:
        session.close()
