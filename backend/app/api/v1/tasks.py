"""Task lifecycle manager API — CRUD, state machine, SSE progress streaming.

POST / dispatches a Celery task that runs the pipeline in a background
worker.  GET /{task_id}/stream provides real-time SSE progress events by
polling Celery's ``AsyncResult`` (Redis-backed, no DB writes for ticks).

Data flow::

  Main (FastAPI):
    1. Load novel data from DB
    2. Serialize to PipelineInput (Redis)
    3. Dispatch Celery task
  Celery Worker:
    1. Read PipelineInput from Redis
    2. Run pipeline (no DB access)
    3. Return PipelineOutput via Celery result backend
  Main (FastAPI):
    1. Detect SUCCESS via AsyncResult (SSE)
    2. Read PipelineOutput from Redis
    3. Persist results to DB
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.celery_app import celery_app
from app.core.db import get_db
from app.core.redis import get_redis
from app.models.http import BaseResponse
from app.models.sql import AuditLog, Chapter as ChapterModel, KnowledgeEdge, KnowledgeNode, Novel, Script, Task, User
from app.services.base import BaseCRUD
from app.services.pipeline_dto import (
    ChapterData,
    KnowledgeGraphData,
    KGEdgeData,
    KGNodeData,
    PipelineInput,
    store_pipeline_input,
    load_pipeline_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    """Body for POST /api/v1/tasks/."""
    novel_id: str = Field(..., description="Novel UUID")
    pipeline_config: dict = Field(default_factory=dict, description="Optional pipeline overrides")
    style_direction: str = Field("", description="Optional AI scriptwriting direction")


class UpdateTaskStatusRequest(BaseModel):
    """Body for PUT /api/v1/tasks/{task_id}/status."""
    status: str = Field(..., description="Target status")
    progress: int | None = Field(None, ge=0, le=100, description="Progress percentage")
    error_message: str | None = Field(None, description="Error details on failure")

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# ---------------------------------------------------------------------------
# CRUD instances
# ---------------------------------------------------------------------------
task_crud = BaseCRUD[Task](Task)
novel_crud = BaseCRUD[Novel](Novel)
audit_crud = BaseCRUD[AuditLog](AuditLog)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":       {"preprocessing", "converting", "failed"},
    "preprocessing": {"converting", "failed"},
    "converting":    {"completed", "failed"},
    "failed":        {"converting"},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_audit(
    db: Session,
    task_id: uuid.UUID,
    level: str = "info",
    category: str = "task_status",
    message: str = "",
    detail: dict | None = None,
) -> None:
    """Write an audit-log entry for a task status change."""
    entry = AuditLog(
        task_id=task_id,
        level=level,
        category=category,
        message=message,
        detail=detail or {},
    )
    audit_crud.create(db, entry)


# ===================================================================
# POST /api/tasks
# ===================================================================


@router.post("/")
def create_task(
    body: CreateTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    r = Depends(get_redis),
):
    """Create a new conversion task for a novel.

    Data flow:
    1. Load novel + chapters + KG from DB
    2. Serialize to PipelineInput and store in Redis
    3. Dispatch Celery worker (no DB access from worker)
    4. Returns ``{task_id, status: "pending"}`` on success.
    """
    try:
        novel_id = uuid.UUID(body.novel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid novel_id: {body.novel_id!r}")

    # Validate novel exists
    novel = novel_crud.get(db, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail=f"Novel {novel_id} not found")
    require_ownership(novel, current_user, resource_name="小说", action="转换")

    # Merge style_direction into pipeline_config for DB persistence
    pipeline_config = dict(body.pipeline_config or {})
    if body.style_direction:
        pipeline_config["style_direction"] = body.style_direction

    task = Task(
        novel_id=novel_id,
        user_id=current_user.id,
        status="pending",
        progress=0,
        pipeline_config=pipeline_config,
    )
    task = task_crud.create(db, task)
    db.commit()

    task_id_str = str(task.id)
    logger.info("Task %s created for novel %s", task_id_str, novel_id)

    # ── Load novel data from DB ───────────────────────────────────────
    source_text = (novel.source_text or "").strip()
    novel_title = novel.title or ""

    # Load chapters
    chapter_rows = (
        db.query(ChapterModel)
        .filter(ChapterModel.novel_id == novel_id)
        .order_by(ChapterModel.chapter_index.asc())
        .all()
    )
    chapters: list[ChapterData] = []
    embeddings_map: dict[int, list[float]] = {}
    for ch in chapter_rows:
        chapters.append(ChapterData(
            index=ch.chapter_index,
            title=ch.title or f"第{ch.chapter_index+1}章",
            text=ch.content or "",
        ))
        if ch.embedding is not None and len(ch.embedding) > 0:
            embeddings_map[ch.chapter_index] = list(ch.embedding)

    # Load cached KG
    kg_nodes = (
        db.query(KnowledgeNode)
        .filter(KnowledgeNode.novel_id == novel_id)
        .all()
    )
    cached_kg = None
    if kg_nodes:
        # Rebuild type prefix map (mirrors pipeline_executor._TYPE_PREFIX)
        type_prefix: dict[str, str] = {
            "character": "char", "location": "loc", "item": "item",
            "event": "event", "organization": "org",
        }
        id_map: dict[uuid.UUID, str] = {}
        cli_nodes: list[KGNodeData] = []
        counters: dict[str, int] = {}
        for n in kg_nodes:
            prefix = type_prefix.get(n.node_type, "node")
            idx = counters.get(prefix, 0) + 1
            counters[prefix] = idx
            cli_id = f"{prefix}_{idx:02d}"
            id_map[n.id] = cli_id
            cli_nodes.append(KGNodeData(
                id=cli_id, label=n.name, type=n.node_type,
                metadata={
                    **(n.properties or {}),
                    "aliases": n.aliases or [],
                    "description": n.description or "",
                },
            ))

        node_uuids = list(id_map.keys())
        cli_edges: list[KGEdgeData] = []
        if node_uuids:
            db_edges = (
                db.query(KnowledgeEdge)
                .filter(
                    KnowledgeEdge.novel_id == novel_id,
                    KnowledgeEdge.source_node_id.in_(node_uuids),
                    KnowledgeEdge.target_node_id.in_(node_uuids),
                )
                .all()
            )
            for e in db_edges:
                src = id_map.get(e.source_node_id)
                tgt = id_map.get(e.target_node_id)
                if src and tgt:
                    cli_edges.append(KGEdgeData(source=src, target=tgt, relation=e.relation, weight=e.weight or 1.0))

        cached_kg = KnowledgeGraphData(nodes=cli_nodes, edges=cli_edges)

    # ── Build PipelineInput and store in Redis ────────────────────────
    pipeline_input = PipelineInput(
        task_id=task_id_str,
        novel_id=str(novel_id),
        source_text=source_text,
        novel_title=novel_title,
        style_direction=body.style_direction,
        chapters=chapters,
        embeddings_map=embeddings_map,
        cached_kg=cached_kg,
    )

    # Graceful degradation: if Redis is down, pipeline input will be read
    # from DB by the Celery worker (fallback).
    try:
        store_pipeline_input(r, task_id_str, pipeline_input)
        logger.info("Pipeline input stored in Redis for task %s", task_id_str)
    except Exception:
        logger.warning("Redis unavailable — pipeline input not cached. Worker will read from DB.")

    # ── Acquire distributed lock (prevents double-dispatch) ────────────
    from app.services.task_lock import try_acquire_task_lock, release_task_lock

    if not try_acquire_task_lock(task_id_str):
        logger.info("Task %s is already locked — another dispatch is in progress.", task_id_str)
        return BaseResponse(
            code=200,
            message="Task already being processed",
            data={"task_id": task_id_str, "status": task.status},
        )

    lock_held = True

    # ── dispatch pipeline ────────────────────────────────────────────
    # Try Celery first; fall back to Redis simple queue on failure.
    try:
        try:
            from app.tasks.pipeline import run_pipeline

            celery_kwargs: dict = {}
            if body.style_direction:
                celery_kwargs["style_direction"] = body.style_direction

            run_pipeline.apply_async(
                args=(task_id_str, str(novel_id)),
                kwargs=celery_kwargs,
                task_id=task_id_str,
                expires=7200,
            )
            logger.info("Task %s dispatched via Celery.", task_id_str)
        except Exception as exc:
            logger.warning(
                "Celery unavailable for task %s: %s — falling back to simple queue.",
                task_id_str, exc,
            )
            from app.services.simple_queue import enqueue_pipeline
            enqueued = enqueue_pipeline(task_id_str, str(novel_id), body.style_direction)
            if enqueued:
                logger.info("Task %s enqueued to simple queue.", task_id_str)
            else:
                logger.error("Failed to enqueue task %s — no worker will process it.", task_id_str)
    except Exception:
        release_task_lock(task_id_str)
        lock_held = False
        raise

    return BaseResponse(
        code=200,
        message="Task created",
        data={"task_id": task_id_str, "status": task.status},
    )


# ===================================================================
# GET /api/tasks
# ===================================================================


@router.get("/")
def list_tasks(
    novel_id: Optional[str] = Query(None, description="Filter by novel UUID"),
    status: Optional[str] = Query(None, description="Filter by task status"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tasks with optional filters and pagination."""
    filters: dict[str, object] = {}
    if novel_id:
        try:
            filters["novel_id"] = uuid.UUID(novel_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid novel_id: {novel_id!r}")
    if status:
        filters["status"] = status

    offset = (page - 1) * limit
    rows, total = task_crud.list(db, offset=offset, limit=limit, filters=filters)

    return BaseResponse(
        code=200,
        message="Tasks retrieved",
        data={
            "tasks": [
                {
                    "id": str(t.id),
                    "novel_id": str(t.novel_id),
                    "status": t.status,
                    "progress": t.progress,
                    "summary": t.summary,
                    "error_message": t.error_message,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in rows
            ],
            "total": total,
            "page": page,
            "limit": limit,
        },
    )


# ===================================================================
# GET /api/tasks/{task_id}/stream  (declared BEFORE /{task_id}/status
# so FastAPI matches "/stream" before the generic path param)
# ===================================================================


@router.get("/{task_id}/stream")
async def stream_progress(
    task_id: str,
    db: Session = Depends(get_db),
    r = Depends(get_redis),
):
    """SSE endpoint — streams pipeline progress events in real time.

    Polls Celery's ``AsyncResult`` (Redis) for progress.  No DB writes
    are triggered for incremental progress ticks — only the final state
    (completed / failed) lands in the database.

    Returns ``text/event-stream``.  Events:

    * ``progress`` — ``{progress: int, stage: str}``
    * ``complete`` — ``{progress: 100}`` (stream closes)
    * ``error``   — ``{error: str}`` (stream closes)
    * ``heartbeat`` — empty data, keeps connection alive

    If the task is already completed or failed when the client connects,
    a single final event is yielded and the stream closes immediately.
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    # ── quick sync check: task exists in DB? ────────────────────────────
    task = db.get(Task, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Celery AsyncResult — reads state from Redis (same broker as worker)
    result = AsyncResult(str(tid), app=celery_app)

    async def _event_generator():
        # If already terminal in DB, exit immediately (worker done before SSE connected)
        if task.status == "completed":
            yield {"event": "complete", "data": json.dumps({"progress": 100}, ensure_ascii=False)}
            return
        if task.status == "failed":
            err = task.error_message or "Unknown error"
            yield {"event": "error", "data": json.dumps({"error": str(err)}, ensure_ascii=False)}
            return

        last_progress = -1
        last_stage = ""

        while True:
            try:
                state = result.state
                info = result.info if result.info else {}
            except Exception:
                # Redis temporarily unavailable — heartbeat + retry
                await asyncio.sleep(1.0)
                yield {"event": "heartbeat", "data": ""}
                continue

            if state == "PROGRESS":
                p = info.get("progress", last_progress)
                s = info.get("stage", last_stage)
                # Derive task status from stage (same logic as Celery _on_progress)
                ss = "preprocessing" if s in ("starting", "chunking", "summarizing", "graphrag", "rag") else "converting"
                # Only emit if something changed (avoid redundant events)
                if p != last_progress or s != last_stage:
                    last_progress = p
                    last_stage = s
                    yield {
                        "event": "progress",
                        "data": json.dumps({"progress": p, "stage": s, "status": ss}, ensure_ascii=False),
                    }
            elif state == "SUCCESS":
                # Read PipelineOutput from Redis and persist to DB
                data: dict = {"progress": 100}
                try:
                    from app.services.pipeline_executor import persist_pipeline_output
                    from app.services.task_lock import release_task_lock

                    output = load_pipeline_result(r, task_id)
                    if output and output.status == "completed":
                        script_id = persist_pipeline_output(
                            db, output, tid,
                            uuid.UUID(output.novel_id) if output.novel_id else tid,
                        )
                        if script_id:
                            data["script_id"] = script_id
                            logger.info("Pipeline output persisted for task %s (script=%s).", task_id, script_id)
                    elif output and output.status == "failed":
                        # Persist failure status
                        failed_task = db.get(Task, tid)
                        if failed_task:
                            failed_task.status = "failed"
                            failed_task.error_message = (output.error_message or "Pipeline failed")[:5000]
                            failed_task.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                            db.add(failed_task)
                            db.commit()
                        data["error"] = output.error_message or "Pipeline failed"
                    # Release lock on terminal state
                    release_task_lock(task_id)
                except Exception as exc:
                    logger.exception("Failed to persist pipeline output for task %s.", task_id)
                    data["error"] = str(exc)
                yield {"event": "complete", "data": json.dumps(data, ensure_ascii=False)}
                return
            elif state == "FAILURE":
                err_msg = str(info) if info else "Pipeline failed"
                yield {"event": "error", "data": json.dumps({"error": err_msg}, ensure_ascii=False)}
                return
            elif state == "REVOKED":
                yield {"event": "error", "data": json.dumps({"error": "Task was revoked"}, ensure_ascii=False)}
                return
            else:
                # PENDING / STARTED — waiting for worker to pick up
                pass

            await asyncio.sleep(0.5)
            yield {"event": "heartbeat", "data": ""}

    return EventSourceResponse(_event_generator())


# ===================================================================
# GET /api/tasks/{task_id}/status  (declared BEFORE /{task_id} to
# avoid FastAPI matching the literal "/status" as a task_id)
# ===================================================================


@router.get("/{task_id}/status")
def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get lightweight task status (no full artifact payload)."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return BaseResponse(
        code=200,
        message="Status retrieved",
        data={
            "task_id": str(task.id),
            "status": task.status,
            "progress": task.progress,
            "error_message": task.error_message,
        },
    )


# ===================================================================
# PUT /api/tasks/{task_id}/status
# ===================================================================


@router.put("/{task_id}/status")
def update_task_status(
    task_id: str,
    body: UpdateTaskStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update task status with state-machine enforcement.

    Valid transitions (skip-stage transitions return 422):

    - pending      -> preprocessing | converting | failed
    - preprocessing -> converting | failed
    - converting    -> completed | failed
    - failed        -> converting
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    require_ownership(task, current_user, resource_name="任务", action="修改")

    new_status = body.status
    current_status = task.status
    updates: dict = {}

    # Enforce state machine if status is changing
    if new_status != current_status:
        allowed = VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid transition: {current_status} -> {new_status}",
            )

        updates["status"] = new_status

        # Write audit log
        _write_audit(
            db,
            task.id,
            category="task_status",
            message=f"Status transition: {current_status} -> {new_status}",
            detail={"from": current_status, "to": new_status},
        )

    # Optional field updates
    if body.progress is not None:
        updates["progress"] = body.progress
    if body.error_message is not None:
        updates["error_message"] = body.error_message

    if updates:
        task = task_crud.update(db, task.id, updates)
        if task is None:
            raise HTTPException(status_code=500, detail="Failed to update task")

    return BaseResponse(
        code=200,
        message="Status updated",
        data={
            "task_id": str(task.id),
            "status": task.status,
            "progress": task.progress,
            "error_message": task.error_message,
        },
    )


# ===================================================================
# POST /api/tasks/{task_id}/resume
# ===================================================================


@router.post("/{task_id}/resume")
def resume_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    r = Depends(get_redis),
):
    """Resume a failed task (failed -> converting).

    Data flow: reload novel data from DB, store in Redis, dispatch Celery.
    Returns 422 if the task is not in ``failed`` status.
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    require_ownership(task, current_user, resource_name="任务", action="恢复")

    if task.status != "failed":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Task {task_id} has status '{task.status}'; "
                "only 'failed' tasks can be resumed"
            ),
        )

    task = task_crud.update(
        db,
        task.id,
        {"status": "converting", "error_message": None},
    )

    _write_audit(
        db,
        task.id,
        category="task_status",
        message="Task resumed: failed -> converting",
        detail={"from": "failed", "to": "converting"},
    )

    db.commit()

    # ── Reload novel data and store PipelineInput in Redis ──────────────
    novel_id = task.novel_id
    novel = novel_crud.get(db, novel_id)
    if novel:
        source_text = (novel.source_text or "").strip()
        novel_title = novel.title or ""

        chapter_rows = (
            db.query(ChapterModel)
            .filter(ChapterModel.novel_id == novel_id)
            .order_by(ChapterModel.chapter_index.asc())
            .all()
        )
        chapters = [
            ChapterData(index=ch.chapter_index, title=ch.title or f"第{ch.chapter_index+1}章", text=ch.content or "")
            for ch in chapter_rows
        ]
        embeddings_map = {
            ch.chapter_index: list(ch.embedding)
            for ch in chapter_rows if ch.embedding is not None and len(ch.embedding) > 0
        }

        # Rebuild style direction
        style_direction = (task.pipeline_config or {}).get("style_direction", "")

        pipeline_input = PipelineInput(
            task_id=str(task.id), novel_id=str(novel_id),
            source_text=source_text, novel_title=novel_title,
            style_direction=style_direction,
            chapters=chapters, embeddings_map=embeddings_map,
        )
        try:
            store_pipeline_input(r, str(task.id), pipeline_input)
        except Exception:
            logger.warning("Redis unavailable — pipeline input not cached for resume.")

    # ── Acquire distributed lock (prevents double-dispatch) ──────────
    from app.services.task_lock import try_acquire_task_lock, release_task_lock

    task_id_str = str(task.id)
    if not try_acquire_task_lock(task_id_str):
        logger.warning("Task %s is locked — another worker is already processing it.", task_id_str)
        return BaseResponse(
            code=200,
            message="Task already being processed by another worker",
            data={"task_id": task_id_str, "status": "converting"},
        )

    # ── re-dispatch pipeline ─────────────────────────────────────────
    # Try Celery first; fall back to Redis simple queue on failure.
    stored_style = (task.pipeline_config or {}).get("style_direction", "")
    lock_held = True
    try:
        try:
            from app.tasks.pipeline import run_pipeline

            celery_kwargs: dict = {}
            if stored_style:
                celery_kwargs["style_direction"] = stored_style

            run_pipeline.apply_async(
                args=(task_id_str, str(novel_id)),
                kwargs=celery_kwargs,
                task_id=task_id_str,
                expires=7200,
            )
            logger.info("Task %s re-dispatched via Celery.", task_id_str)
        except Exception as exc:
            logger.warning(
                "Celery unavailable for resume of task %s: %s — falling back to simple queue.",
                task_id_str, exc,
            )
            from app.services.simple_queue import enqueue_pipeline
            enqueued = enqueue_pipeline(task_id_str, str(novel_id), stored_style)
            if enqueued:
                logger.info("Task %s enqueued to simple queue.", task_id_str)
            else:
                logger.error("Failed to enqueue resumed task %s.", task_id_str)
    except Exception:
        release_task_lock(task_id_str)
        lock_held = False
        raise

    return BaseResponse(
        code=200,
        message="Task resumed",
        data={"task_id": str(task.id), "status": task.status},
    )


# ===================================================================
# DELETE /api/tasks/{task_id}  (declared BEFORE GET /{task_id})
# ===================================================================


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a task. Only allowed on terminal-status tasks (completed/failed)."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    require_ownership(task, current_user, resource_name="任务", action="删除")

    if task.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Task {task_id} has status '{task.status}'; "
                "only 'completed' or 'failed' tasks can be deleted"
            ),
        )

    task_crud.delete(db, tid)
    return BaseResponse(
        code=200,
        message="Task deleted",
        data={"deleted_id": str(task_id)},
    )


# ===================================================================
# GET /api/tasks/{task_id}  (MUST be last — most generic pattern)
# ===================================================================


@router.get("/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full task detail including progress, error_message, and script artifacts."""
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return BaseResponse(
        code=200,
        message="Task retrieved",
        data={
            "id": str(task.id),
            "novel_id": str(task.novel_id),
            "user_id": str(task.user_id) if task.user_id else None,
            "status": task.status,
            "progress": task.progress,
            "summary": task.summary,
            "characters_json": task.characters_json,
            "script_yaml": task.script_yaml,
            "script_json": task.script_json,
            "script_fountain": task.script_fountain,
            "error_message": task.error_message,
            "pipeline_config": task.pipeline_config,
            "token_usage": task.token_usage,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        },
    )
