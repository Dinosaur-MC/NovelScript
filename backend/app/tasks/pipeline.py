"""Celery task — runs the novel-to-script pipeline in a background worker.

Dispatched by ``POST /novels/upload`` (auto) or ``POST /tasks`` (manual).
Progress is reported through Celery's built-in ``self.update_state()``
which writes to Redis; the FastAPI SSE endpoint reads it back via
``AsyncResult(task_id)`` — no DB writes for incremental progress ticks.

Only the final result (completed / failed) is persisted to the database.

Concurrency model
-----------------
Celery natively handles queuing + concurrency:

- ``apply_async()``           → task lands in Redis broker queue
- ``worker_prefetch_multiplier=1`` → each worker grabs only 1 task at a time
- ``--concurrency=N``        → at most N tasks run concurrently per worker
- ``task_acks_late=True``    → task re-queued if worker crashes mid-execution

Inside each pipeline run, ``asyncio.Semaphore(LLM_MAX_CONCURRENCY)`` gates
the 3 concurrent LLM stages (Summarization / Conversion / Optimization)
so the LLM API is never flooded even within a single task.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.db import _session_factory
from app.models.sql import (
    Chapter as ChapterModel,
    KnowledgeEdge,
    KnowledgeNode,
    Novel,
    Task,
)
from cli.exporter import to_yaml
from cli.fountain_exporter import to_fountain
from cli.models import Chapter, KnowledgeEdge as CLIEdge
from cli.models import KnowledgeGraph, KnowledgeNode as CLINode
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


# =============================================================================
# Public Celery task
# =============================================================================


@celery_app.task(
    bind=True,
    name="pipeline.run",
    max_retries=0,
    soft_time_limit=7200,  # 2h before Celery kills and re-queues
    time_limit=7800,       # 2h 10m — hard limit
)
def run_pipeline(self, task_id: str, novel_id: str, style_direction: str = "") -> dict:
    """Execute the full novel-to-script pipeline for *task_id*.

    Args:
        task_id:  Task UUID string (also used as the Celery task id so
                  ``AsyncResult(task_id)`` works from FastAPI).
        novel_id: Novel UUID string.
        style_direction:  Optional AI scriptwriting / style instruction
                  injected into Conversion and Optimization prompts.

    Returns:
        ``{"status": "completed", "scenes": N}`` on success.

    Celery queues excess tasks automatically in Redis — if all workers are
    busy, new tasks wait in the broker until a worker is free.
    """
    tid = uuid.UUID(task_id)
    nid = uuid.UUID(novel_id)
    session = _session_factory()

    try:
        # ---- validate task state ---------------------------------------------
        # Celery may re-queue stale/duplicate tasks on restart.  Only run if
        # the task is in a valid starting state (pending or failed → resume).
        task = session.get(Task, tid)
        if task is None:
            logger.warning("Task %s not found in DB — skipping.", task_id)
            session.close()
            return {"status": "skipped", "reason": "task not found"}
        if task.status not in ("pending", "failed"):
            logger.info(
                "Task %s has status '%s' — skipping (only pending/failed tasks can run).",
                task_id, task.status,
            )
            session.close()
            return {"status": "skipped", "reason": f"invalid status: {task.status}"}
        # Stale task guard: if a pending task is older than 3h, it's from a
        # previous session and should not be executed (the caller should
        # create a fresh task instead).
        if task.created_at:
            age = (datetime.now(timezone.utc) - task.created_at).total_seconds()
            if age > 10800:  # 3 hours
                logger.info(
                    "Task %s is %d seconds old (>3h) — skipping stale task.",
                    task_id, int(age),
                )
                session.close()
                return {"status": "skipped", "reason": f"stale task ({int(age)}s old)"}

        # ---- load novel -------------------------------------------------
        novel = session.get(Novel, nid)
        if novel is None:
            _fail(session, tid, f"Novel {novel_id} not found.")
            session.close()
            return {"status": "failed", "error": f"Novel {novel_id} not found."}

        source = (novel.source_text or "").strip()
        if not source:
            logger.warning("Novel %s has no source_text — task stays pending.", nid)
            session.close()
            return {"status": "pending", "reason": "empty source"}

        # ---- progress callback (Redis-only via Celery built-in state) ---
        def _on_progress(progress: int, stage: str) -> None:
            try:
                # Update DB for state machine transitions (infrequent)
                task = session.get(Task, tid)
                if task is None:
                    return
                current_status = task.status
                if stage in ("starting", "chunking", "summarizing", "graphrag", "rag"):
                    if current_status == "pending":
                        task.status = "preprocessing"
                elif stage in ("converting",):
                    if current_status in ("pending", "preprocessing"):
                        task.status = "converting"
                if task.status != current_status:
                    task.updated_at = datetime.now(timezone.utc)
                    session.add(task)
                    session.commit()

                # Report progress to Redis (no DB write for the % value)
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "stage": stage},
                )
            except Exception:
                logger.exception("Progress callback failed (ignored).")
                session.rollback()

        # ---- load cache from DB -----------------------------------------
        from app.services.pipeline_executor import (
            _load_chapters,
            _load_cached_kg,
        )
        from cli.pipeline import run_from_chapters, run_from_text

        chapters, embeddings_map = _load_chapters(session, nid)
        cached_kg = _load_cached_kg(session, nid)

        # ---- build FAISS from cached embeddings --------------------------
        if chapters and embeddings_map:
            from cli.rag_builder import build_index_from_db_embeddings

            faiss_index = build_index_from_db_embeddings(chapters, embeddings_map)
        else:
            faiss_index = None

        # ---- run pipeline ------------------------------------------------
        if chapters:
            script = asyncio.run(
                run_from_chapters(
                    chapters,
                    progress_callback=_on_progress,
                    source_name=novel.title or str(nid),
                    faiss_index=faiss_index,
                    kg=cached_kg,
                    style_direction=style_direction,
                )
            )
        else:
            script = asyncio.run(
                run_from_text(
                    source,
                    progress_callback=_on_progress,
                    source_name=novel.title or str(nid),
                    style_direction=style_direction,
                )
            )

        # ---- persist final results to DB ---------------------------------
        from app.services.pipeline_executor import (
            _persist_chapters,
            _persist_embeddings,
            _persist_kg,
        )

        task = session.get(Task, tid)
        if task is None:
            return {"status": "failed", "error": f"Task {task_id} not found."}

        task.status = "completed"
        task.progress = 100
        task.summary = script.summary
        task.script_yaml = to_yaml(script)
        task.script_json = script.model_dump(mode="json")
        task.script_fountain = to_fountain(script)
        task.characters_json = [
            {"id": c.id, "name": c.name, "aliases": c.aliases, "properties": c.properties, "node_type": "character"}
            for c in script.characters
        ]
        # Persist token usage from the pipeline's meta output
        task.token_usage = script.meta.get("usage", {})
        task.updated_at = datetime.now(timezone.utc)
        session.add(task)

        # v3: populate Script entity
        from app.models.sql import Script as ScriptModel
        if task.script_id:
            script_row = session.get(ScriptModel, task.script_id)
        else:
            script_row = None
        if script_row is None:
            script_row = ScriptModel(
                novel_id=nid,
                user_id=task.user_id,
                title=task.summary or "Generated Script",
                source_type="generated",
            )
            session.add(script_row)
            session.flush()
            task.script_id = script_row.id
            session.add(task)
        script_row.script_yaml = task.script_yaml
        script_row.script_json = task.script_json
        script_row.script_fountain = task.script_fountain
        script_row.characters_json = task.characters_json
        script_row.summary = task.summary
        script_row.token_usage = task.token_usage
        script_row.status = "completed"
        script_row.updated_at = datetime.now(timezone.utc)
        session.add(script_row)

        # ── Commit main result first (Script + Task = completed) ────────
        # This ensures the pipeline output is saved even if cache persistence
        # fails (e.g. UniqueViolation from a concurrent pipeline run).
        session.commit()
        logger.info(
            "Pipeline completed for task %s: %d scenes.",
            task_id, len(script.scenes),
        )

        # ── Cache for future runs (best-effort, independent transaction) ─
        # If another worker already cached this data, IntegrityError is
        # caught and logged — no effect on the completed pipeline result.
        try:
            if not chapters:
                _persist_chapters(session, nid, script.meta.get("chapter_summaries", []))
            if not embeddings_map and faiss_index is None:
                _persist_embeddings(session, nid, source, script)
            if cached_kg is None:
                _persist_kg(session, script, tid, nid, script_row.id if script_row else None)
            session.commit()
        except IntegrityError:
            session.rollback()
            logger.info("Cache persistence skipped (already cached by another pipeline run).")

        session.close()

        total_cost = script.meta.get("usage", {}).get("total_cost_yuan", 0)
        logger.info("Pipeline cost: ¥%.4f.", total_cost)
        return {"status": "completed", "scenes": len(script.scenes)}

    except Exception:
        logger.exception("Pipeline failed for task %s.", task_id)
        msg = traceback.format_exc()
        _fail(session, tid, msg)
        session.close()
        return {"status": "failed", "error": msg}


# =============================================================================
# Internal
# =============================================================================


def _fail(session, task_id: uuid.UUID, message: str) -> None:
    """Persist ``failed`` status to DB."""
    try:
        task = session.get(Task, task_id)
        if task is not None:
            task.status = "failed"
            task.error_message = message[:5000]
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
    except Exception:
        logger.exception("Failed to persist failure for task %s.", task_id)
        session.rollback()
