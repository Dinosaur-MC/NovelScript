"""Task lifecycle manager API — CRUD, state machine, SSE progress streaming.

POST / creates a task and spawns a background daemon thread that runs the
pipeline.  GET /{task_id}/stream provides real-time SSE progress events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import AuditLog, Novel, Task, User
from app.services.base import BaseCRUD
from app.services.progress import progress_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    """Body for POST /api/v1/tasks/."""
    novel_id: str = Field(..., description="Novel UUID")
    pipeline_config: dict = Field(default_factory=dict, description="Optional pipeline overrides")


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
    Immediately spawns a background daemon thread that runs the pipeline.
    """
    try:
        novel_id = uuid.UUID(body.novel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid novel_id: {body.novel_id!r}")

    # Validate novel exists
    novel = novel_crud.get(db, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail=f"Novel {novel_id} not found")

    task = Task(
        novel_id=novel_id,
        user_id=current_user.id,
        status="pending",
        progress=0,
        pipeline_config=body.pipeline_config,
    )
    task = task_crud.create(db, task)

    logger.info("Task %s created for novel %s", task.id, novel_id)

    # ── commit BEFORE spawning background thread ──────────────────────
    # The background thread opens its own independent session.  Without
    # an explicit commit, the thread may not see the new Task row (race
    # with the outer get_db() commit).
    db.commit()

    # ── kick off pipeline in background thread ────────────────────────
    from app.services.pipeline_executor import execute_pipeline

    execute_pipeline(task.id, novel_id)

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

    # ── quick sync check: task exists? ──────────────────────────────────
    task = db.get(Task, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    q = progress_manager.create_queue(str(tid))

    async def _event_generator():
        try:
            # If the task already reached a terminal state before the SSE
            # client connected, push one final event and exit immediately.
            if task.status == "completed":
                yield {"event": "complete", "data": json.dumps({"progress": 100}, ensure_ascii=False)}
                return
            if task.status == "failed":
                err = task.error_message or "Unknown error"
                yield {"event": "error", "data": json.dumps({"error": str(err)}, ensure_ascii=False)}
                return

            # Main poll loop
            while True:
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.5)
                    yield {"event": "heartbeat", "data": ""}
                    continue

                event_type = event.get("type", "")
                data = event.get("data", {})

                if event_type == "progress":
                    yield {
                        "event": "progress",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                elif event_type == "complete":
                    yield {
                        "event": "complete",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                    return
                elif event_type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                    return
        finally:
            progress_manager.remove_queue(str(tid))

    return EventSourceResponse(_event_generator())


# ===================================================================
# GET /api/tasks/{task_id}/status  (declared BEFORE /{task_id} to
# avoid FastAPI matching the literal "/status" as a task_id)
# ===================================================================


@router.get("/{task_id}/status")
def get_task_status(task_id: str, db: Session = Depends(get_db)):
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

    # ── commit BEFORE spawning background thread (race-condition fix) ──
    db.commit()

    # ── re-spawn the pipeline ─────────────────────────────────────────
    from app.services.pipeline_executor import execute_pipeline

    execute_pipeline(task.id, task.novel_id)

    return BaseResponse(
        code=200,
        message="Task resumed",
        data={"task_id": str(task.id), "status": task.status},
    )


# ===================================================================
# GET /api/tasks/{task_id}  (MUST be last — most generic pattern)
# ===================================================================


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
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
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        },
    )
