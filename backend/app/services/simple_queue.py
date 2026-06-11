"""Redis-based simple task queue — Celery fallback for single-machine deployments.

When Celery is unavailable (broker unreachable), tasks are queued via
Redis lists (LPUSH/BRPOP) and processed by a background worker running
inside the Main (FastAPI) process.

Data flow::

  API → Redis list ──→ Main background worker ──→ pipeline result → Redis
                                                         ↓
                                              Main result watcher → DB

Architecture:
- Queue: Redis list key "pipeline:queue" (FIFO via LPUSH + BRPOP)
- Worker: asyncio background task in FastAPI lifespan
- Worker runs the pipeline inline (same process) via asyncio
- Progress is reported through the same PipelineOutput → Redis mechanism
- The existing result watcher (main.py) picks up results and persists to DB
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

QUEUE_KEY = "pipeline:queue"


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue_pipeline(
    task_id: str,
    novel_id: str,
    style_direction: str = "",
) -> bool:
    """Push a pipeline task onto the Redis simple queue.

    Returns True if enqueued, False if Redis is unavailable.
    """
    try:
        from app.core.redis import get_redis_client

        r = get_redis_client()
        if r is None:
            return False

        data = json.dumps({
            "task_id": task_id,
            "novel_id": novel_id,
            "style_direction": style_direction,
        }, ensure_ascii=False)
        r.lpush(QUEUE_KEY, data)
        logger.info("Task %s enqueued to simple queue for novel %s.", task_id, novel_id)
        return True
    except Exception as exc:
        logger.warning("Failed to enqueue task %s to simple queue: %s", task_id, exc)
        return False


# ---------------------------------------------------------------------------
# Worker loop — runs in Main process as asyncio background task
# ---------------------------------------------------------------------------


async def worker_loop():
    """Background worker: pop tasks from Redis queue and run pipeline inline.

    Runs as an asyncio task inside FastAPI's lifespan.
    Cancelled on shutdown via asyncio.CancelledError.
    """
    logger.info("Simple queue worker started (key=%s).", QUEUE_KEY)

    while True:
        try:
            from app.core.redis import get_redis_client

            r = get_redis_client()
            if r is None:
                await asyncio.sleep(5)
                continue

            # Blocking pop with timeout (allows clean CancelledError handling)
            try:
                result = r.brpop(QUEUE_KEY, timeout=5)
            except Exception:
                await asyncio.sleep(1)
                continue

            if result is None:
                # Timeout — no task in queue, loop back
                continue

            # result = (queue_key, data_str)
            _, data_str = result

            try:
                data = json.loads(data_str)
                task_id = data["task_id"]
                novel_id = data["novel_id"]
                style = data.get("style_direction", "")

                logger.info("Simple queue worker picked up task %s.", task_id)

                # ── Distributed lock: skip if Celery already claimed this task ─
                from app.services.task_lock import try_acquire_task_lock, release_task_lock

                if not try_acquire_task_lock(task_id):
                    logger.info(
                        "Task %s is locked (Celery took over) — removing from simple queue.",
                        task_id,
                    )
                    continue

                # Load pipeline input
                from app.services.pipeline_dto import (
                    PipelineOutput,
                    load_pipeline_input,
                    store_pipeline_result,
                )

                pipeline_input = load_pipeline_input(r, task_id)
                if pipeline_input is None:
                    logger.error("Pipeline input not found for task %s — skipping.", task_id)
                    store_pipeline_result(
                        r, task_id,
                        PipelineOutput(status="failed", error_message="Pipeline input not found in Redis"),
                    )
                    continue

                # Run the pipeline inline
                output = await _run_pipeline_inline(task_id, novel_id, pipeline_input, style)

                # Store result in Redis + release lock
                store_pipeline_result(r, task_id, output)
                release_task_lock(task_id)
                logger.info("Simple queue: task %s completed (status=%s).", task_id, output.status)

            except Exception as exc:
                logger.exception("Simple queue worker error processing task.")
                # Store failure + release lock
                try:
                    from app.core.redis import get_redis_client as grc2
                    from app.services.pipeline_dto import PipelineOutput, store_pipeline_result
                    r2 = grc2()
                    if r2:
                        store_pipeline_result(
                            r2, data.get("task_id", "unknown"),
                            PipelineOutput(status="failed", error_message=str(exc)),
                        )
                    release_task_lock(data.get("task_id", "unknown"))
                except Exception:
                    pass

        except asyncio.CancelledError:
            logger.info("Simple queue worker cancelled.")
            break
        except Exception:
            logger.exception("Simple queue worker error (will retry).")
            await asyncio.sleep(5)


async def _run_pipeline_inline(task_id: str, novel_id: str, pipeline_input, style: str):
    """Run the pipeline in-process (no Celery).

    Mirrors the Celery task logic in app/tasks/pipeline.py but runs
    synchronously in the Main process.
    """
    from cli.exporter import to_yaml
    from cli.fountain_exporter import to_fountain
    from app.services.pipeline_dto import (
        ChapterData, KnowledgeGraphData, KGNodeData, KGEdgeData, PipelineOutput,
    )

    source = (pipeline_input.source_text or "").strip()
    if not source:
        return PipelineOutput(status="pending", error_message="empty source")

    # Reconstruct CLI objects
    from cli.models import Chapter, KnowledgeGraph, KnowledgeNode as CLINode, KnowledgeEdge as CLIEdge

    chapters = [
        Chapter(text=ch.text, title=ch.title, index=ch.index)
        for ch in pipeline_input.chapters
    ]
    cached_kg = None
    if pipeline_input.cached_kg and pipeline_input.cached_kg.nodes:
        cached_kg = KnowledgeGraph(
            nodes=[CLINode(id=n.id, label=n.label, type=n.type, metadata=n.metadata) for n in pipeline_input.cached_kg.nodes],
            edges=[CLIEdge(source=e.source, target=e.target, relation=e.relation, weight=e.weight) for e in pipeline_input.cached_kg.edges],
        )

    # FAISS
    faiss_index = None
    if chapters and pipeline_input.embeddings_map:
        from cli.rag_builder import build_index_from_db_embeddings
        faiss_index = build_index_from_db_embeddings(chapters, pipeline_input.embeddings_map)

    # Progress callback (synchronous — called from pipeline's internal asyncio loop)
    import json as _json

    def _on_progress(progress: int, stage: str) -> None:
        try:
            from app.core.redis import get_redis_client
            r = get_redis_client()
            if r:
                r.setex(f"pipeline:progress:{task_id}", 3600, _json.dumps({"progress": progress, "stage": stage}))
        except Exception:
            pass

    # Run pipeline in a thread (pipeline is I/O-bound for LLM calls)
    import asyncio as _asyncio

    def _run_pipeline():
        import asyncio as _inner_asyncio
        if chapters:
            from cli.pipeline import run_from_chapters
            return _inner_asyncio.run(
                run_from_chapters(
                    chapters,
                    progress_callback=_on_progress,
                    source_name=pipeline_input.novel_title or str(novel_id),
                    faiss_index=faiss_index,
                    kg=cached_kg,
                    style_direction=style or pipeline_input.style_direction,
                )
            )
        else:
            from cli.pipeline import run_from_text
            return _inner_asyncio.run(
                run_from_text(
                    source,
                    progress_callback=_on_progress,
                    source_name=pipeline_input.novel_title or str(novel_id),
                    style_direction=style or pipeline_input.style_direction,
                )
            )

    script = await _asyncio.to_thread(_run_pipeline)

    # Build output
    pipeline_kg = getattr(script, "knowledge_graph", None)
    kg_output = None
    if pipeline_kg and pipeline_kg.nodes:
        kg_output = KnowledgeGraphData(
            nodes=[KGNodeData(id=n.id, label=n.label, type=n.type, metadata=n.metadata) for n in pipeline_kg.nodes],
            edges=[KGEdgeData(source=e.source, target=e.target, relation=e.relation, weight=e.weight) for e in pipeline_kg.edges],
        )

    output = PipelineOutput(
        status="completed",
        scenes=[s.model_dump(mode="json") for s in script.scenes] if hasattr(script, "scenes") else [],
        summary=script.summary if hasattr(script, "summary") else "",
        script_yaml=to_yaml(script),
        script_json=script.model_dump(mode="json"),
        script_fountain=to_fountain(script),
        characters=[
            {"id": c.id, "name": c.name, "aliases": c.aliases, "properties": c.properties, "node_type": "character"}
            for c in (script.characters if hasattr(script, "characters") else [])
        ],
        chapters=pipeline_input.chapters,
        knowledge_graph=kg_output,
        token_usage=script.meta.get("usage", {}) if hasattr(script, "meta") else {},
    )

    return output
