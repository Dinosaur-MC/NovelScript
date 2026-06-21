"""Celery task — runs the novel-to-script pipeline in a background worker.

Refactored data flow (no DB access from Celery)::

  Main (FastAPI):
    1. Load novel data from DB
    2. Serialize to PipelineInput (Redis)
    3. Dispatch Celery task with Redis key reference

  Celery Worker:
    1. Read PipelineInput from Redis
    2. Run pipeline (in-memory only)
    3. Write PipelineOutput to Redis via result backend

  Main (FastAPI):
    1. Detect SUCCESS via AsyncResult (SSE)
    2. Read PipelineOutput from Redis
    3. Persist results to DB
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid

from app.core.celery_app import celery_app
from app.services.pipeline_dto import (
    ChapterData,
    KnowledgeGraphData,
    KGEdgeData,
    KGNodeData,
    PipelineInput,
    PipelineOutput,
    load_pipeline_input,
    store_pipeline_result,
)

from cli.exporter import to_yaml
from cli.fountain_exporter import to_fountain
from cli.models import Chapter, KnowledgeEdge as CLIEdge
from cli.models import KnowledgeGraph, KnowledgeNode as CLINode

logger = logging.getLogger(__name__)


def _reconstruct_kg(kg_data: KnowledgeGraphData | None) -> KnowledgeGraph | None:
    """Reconstruct CLI KnowledgeGraph from DTO."""
    if not kg_data or not kg_data.nodes:
        return None
    nodes = [
        CLINode(id=n.id, label=n.label, type=n.type, metadata=n.metadata)
        for n in kg_data.nodes
    ]
    edges = [
        CLIEdge(source=e.source, target=e.target, relation=e.relation, weight=e.weight)
        for e in kg_data.edges
    ]
    return KnowledgeGraph(nodes=nodes, edges=edges)


def _build_pipeline_chapters(chapters_data: list[ChapterData]) -> list[Chapter]:
    """Build CLI Chapter list from DTO."""
    return [
        Chapter(text=ch.text, title=ch.title, index=ch.index)
        for ch in chapters_data
    ]


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
    """Execute the full novel-to-script pipeline, reading input from Redis.

    Args:
        task_id:  Task UUID (also used as Redis key).
        novel_id: Novel UUID (for result tracking).
        style_direction:  Optional AI scriptwriting direction.

    Returns:
        Dict with results which Celery stores in Redis (result backend).
        The Main process detects completion via AsyncResult and persists.
    """
    tid = uuid.UUID(task_id)

    try:
        # ── Load input from Redis (preferred — no DB access) ─────────────
        from app.core.redis import get_redis_sync

        redis_conn = get_redis_sync()
        pipeline_input = None
        if redis_conn is not None:
            pipeline_input = load_pipeline_input(redis_conn, task_id)

        # ── Fallback: load from DB (legacy path, Redis unavailable) ─────
        if pipeline_input is None:
            logger.warning("Pipeline input not in Redis — falling back to DB for task %s.", task_id)
            from app.core.db import _session_factory
            fallback_session = _session_factory()
            try:
                from app.models.sql import Chapter as ChapterModel, KnowledgeEdge, KnowledgeNode, Novel, Task as TaskModel
                from app.services.pipeline_executor import _load_chapters, _load_cached_kg

                task_row = fallback_session.get(TaskModel, tid)
                if task_row is None:
                    fallback_session.close()
                    return {"status": "failed", "error": f"Task {task_id} not found in DB"}

                novel = fallback_session.get(Novel, tid) if False else None
                novel = fallback_session.query(Novel).filter(Novel.id == task_row.novel_id).first()
                if novel is None:
                    fallback_session.close()
                    # Attempt to find novel directly
                    novel = fallback_session.get(Novel, task_row.novel_id)
                if novel is None:
                    fallback_session.close()
                    return {"status": "failed", "error": f"Novel not found for task {task_id}"}

                source_text = (novel.source_text or "").strip()
                chapters, embeddings_map = _load_chapters(fallback_session, task_row.novel_id)
                cached_kg = _load_cached_kg(fallback_session, task_row.novel_id)

                # Build PipelineInput from DB data
                chapter_data_list = []
                if chapters:
                    for ch in chapters:
                        chapter_data_list.append(ChapterData(
                            index=ch.index, title=ch.title, text=ch.text,
                        ))
                kg_data = None
                if cached_kg:
                    kg_data = KnowledgeGraphData(
                        nodes=[KGNodeData(id=n.id, label=n.label, type=n.type, metadata=n.metadata) for n in cached_kg.nodes],
                        edges=[KGEdgeData(source=e.source, target=e.target, relation=e.relation, weight=e.weight) for e in cached_kg.edges],
                    )
                pipeline_input = PipelineInput(
                    task_id=task_id, novel_id=str(task_row.novel_id),
                    source_text=source_text, novel_title=novel.title or "",
                    style_direction=style_direction,
                    chapters=chapter_data_list,
                    embeddings_map=embeddings_map,
                    cached_kg=kg_data,
                )
            finally:
                fallback_session.close()

        if pipeline_input is None:
            return {"status": "failed", "error": f"Cannot load pipeline input for task {task_id}"}

        source = (pipeline_input.source_text or "").strip()
        if not source:
            return {"status": "pending", "reason": "empty source"}

        # ── Progress callback (Redis-only via Celery built-in state) ────
        def _on_progress(progress: int, stage: str) -> None:
            try:
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "stage": stage},
                )
            except Exception:
                logger.exception("Progress callback failed (ignored).")

        # ── Reconstruct CLI objects ──────────────────────────────────────
        chapters = _build_pipeline_chapters(pipeline_input.chapters)
        cached_kg = _reconstruct_kg(pipeline_input.cached_kg)
        embeddings_map = pipeline_input.embeddings_map

        # ── Build FAISS from cached embeddings ──────────────────────────
        faiss_index = None
        if chapters and embeddings_map:
            from cli.rag_builder import build_index_from_db_embeddings

            faiss_index = build_index_from_db_embeddings(chapters, embeddings_map)

        # ── Run pipeline ─────────────────────────────────────────────────
        if chapters:
            from cli.pipeline import run_from_chapters

            script = asyncio.run(
                run_from_chapters(
                    chapters,
                    progress_callback=_on_progress,
                    source_name=pipeline_input.novel_title or str(novel_id),
                    faiss_index=faiss_index,
                    kg=cached_kg,
                    style_direction=style_direction or pipeline_input.style_direction,
                )
            )
        else:
            from cli.pipeline import run_from_text

            script = asyncio.run(
                run_from_text(
                    source,
                    progress_callback=_on_progress,
                    source_name=pipeline_input.novel_title or str(novel_id),
                    style_direction=style_direction or pipeline_input.style_direction,
                )
            )

        # ── Build PipelineOutput ─────────────────────────────────────────
        pipeline_kg = getattr(script, "knowledge_graph", None)
        kg_output = None
        if pipeline_kg and pipeline_kg.nodes:
            kg_output = KnowledgeGraphData(
                nodes=[
                    KGNodeData(id=n.id, label=n.label, type=n.type, metadata=n.metadata)
                    for n in pipeline_kg.nodes
                ],
                edges=[
                    KGEdgeData(source=e.source, target=e.target, relation=e.relation, weight=e.weight)
                    for e in pipeline_kg.edges
                ],
            )

        output = PipelineOutput(
            status="completed",
            scenes=[s.model_dump(mode="json") for s in script.scenes] if hasattr(script, "scenes") else [],
            summary=script.summary if hasattr(script, "summary") else "",
            script_yaml=to_yaml(script),
            script_json=script.model_dump(mode="json"),
            script_fountain=to_fountain(script),
            characters=[
                {"id": c.id, "name": c.name, "aliases": c.aliases, "properties": c.metadata, "node_type": "character"}
                for c in (script.characters if hasattr(script, "characters") else [])
            ],
            chapters=pipeline_input.chapters,
            knowledge_graph=kg_output,
            token_usage=script.meta.get("usage", {}) if hasattr(script, "meta") else {},
            novel_id=novel_id,
        )

        # ── Store result in Redis for Main process to consume ────────────
        if redis_conn:
            store_pipeline_result(redis_conn, task_id, output)
            logger.info("Pipeline output stored in Redis for task %s.", task_id)

        total_cost = output.token_usage.get("total_cost_yuan", 0)
        logger.info("Pipeline completed for task %s: %d scenes (¥%.4f).", task_id, len(output.scenes), total_cost)

        return output.to_dict()

    except Exception:
        logger.exception("Pipeline failed for task %s.", task_id)
        msg = traceback.format_exc()

        # Store failure in Redis for Main process to consume
        try:
            from app.core.redis import get_redis_sync
            redis_conn = get_redis_sync()
            if redis_conn:
                store_pipeline_result(
                    redis_conn,
                    task_id,
                    PipelineOutput(status="failed", error_message=msg, novel_id=novel_id),
                )
        except Exception:
            logger.exception("Failed to persist failure result to Redis.")

        return {"status": "failed", "error": msg}
