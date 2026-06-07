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

logger = logging.getLogger(__name__)


# =============================================================================
# Public Celery task
# =============================================================================


@celery_app.task(bind=True, name="pipeline.run", max_retries=0)
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

        # Cache for future runs
        if not chapters:
            _persist_chapters(session, nid, script.meta.get("chapter_summaries", []))
        if not embeddings_map and faiss_index is None:
            _persist_embeddings(session, nid, source, script)
        if cached_kg is None:
            _persist_kg(session, script, tid, nid)

        session.commit()
        session.close()

        total_cost = script.meta.get("usage", {}).get("total_cost_yuan", 0)
        logger.info(
            "Pipeline completed for task %s: %d scenes, cost ¥%.4f.",
            task_id, len(script.scenes), total_cost,
        )
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
