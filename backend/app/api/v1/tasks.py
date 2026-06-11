"""Task lifecycle manager API — CRUD, state machine, SSE progress streaming.

POST / dispatches a Celery task that runs the pipeline in a background
worker.  GET /{task_id}/stream provides real-time SSE progress events by
polling Celery's ``AsyncResult`` (Redis-backed, no DB writes for ticks).
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
from sqlalchemy import func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.celery_app import celery_app
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import AuditLog, Novel, Script, Task, User
from app.services.base import BaseCRUD

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
):
    """Create a new conversion task for a novel.

    Returns ``{task_id, status: "pending"}`` on success.
    Immediately dispatches the pipeline to a Celery background worker.
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

    logger.info("Task %s created for novel %s", task.id, novel_id)

    # ── commit BEFORE dispatching Celery task ─────────────────────────
    # The Celery worker opens its own independent DB session.
    db.commit()

    # ── dispatch pipeline to Celery worker ────────────────────────────
    from app.tasks.pipeline import run_pipeline

    celery_kwargs: dict = {}
    if body.style_direction:
        celery_kwargs["style_direction"] = body.style_direction

    run_pipeline.apply_async(
        args=(str(task.id), str(novel_id)),
        kwargs=celery_kwargs,
        task_id=str(task.id),  # so AsyncResult(task_id) works
        expires=7200,          # drop from queue after 2h if not picked up
    )

    return BaseResponse(
        code=200,
        message="Task created",
        data={"task_id": str(task.id), "status": task.status},
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
async def stream_progress(task_id: str, db: Session = Depends(get_db)):
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
                # Only emit if something changed (avoid redundant events)
                if p != last_progress or s != last_stage:
                    last_progress = p
                    last_stage = s
                    yield {
                        "event": "progress",
                        "data": json.dumps({"progress": p, "stage": s}, ensure_ascii=False),
                    }
            elif state == "SUCCESS":
                # Fetch script_id from DB (set by pipeline on completion)
                data: dict = {"progress": 100}
                try:
                    db.expire_all()
                    fresh = db.get(Task, tid)
                    if fresh and fresh.script_id:
                        data["script_id"] = str(fresh.script_id)
                except Exception:
                    pass
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
):
    """Resume a failed task (failed -> converting).

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

    # ── commit BEFORE dispatching Celery task ─────────────────────────
    db.commit()

    # ── re-dispatch pipeline to Celery worker ─────────────────────────
    from app.tasks.pipeline import run_pipeline

    # Restore style_direction from stored pipeline_config
    celery_kwargs: dict = {}
    stored_style = (task.pipeline_config or {}).get("style_direction", "")
    if stored_style:
        celery_kwargs["style_direction"] = stored_style

    run_pipeline.apply_async(
        args=(str(task.id), str(task.novel_id)),
        kwargs=celery_kwargs,
        task_id=str(task.id),
        expires=7200,
    )

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
