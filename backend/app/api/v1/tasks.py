"""Task lifecycle manager API — status tracking only (no pipeline execution).

All routes are synchronous and use the shared ``get_db()`` dependency.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import AuditLog, Novel, Task
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

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
    "pending":       {"preprocessing", "failed"},
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
def create_task(body: dict, db: Session = Depends(get_db)):
    """Create a new conversion task for a novel.

    Body: ``{"novel_id": str, "pipeline_config": {...}?}``

    Returns ``{task_id, status: "pending"}`` on success.
    """
    novel_id_raw = body.get("novel_id")
    if not novel_id_raw:
        raise HTTPException(status_code=400, detail="novel_id is required")

    # Coerce to UUID
    try:
        novel_id = uuid.UUID(novel_id_raw) if isinstance(novel_id_raw, str) else novel_id_raw
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid novel_id: {novel_id_raw!r}")

    # Validate novel exists
    novel = novel_crud.get(db, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail=f"Novel {novel_id} not found")

    pipeline_config = body.get("pipeline_config", {})
    if not isinstance(pipeline_config, dict):
        pipeline_config = {}

    task = Task(
        novel_id=novel_id,
        status="pending",
        progress=0,
        pipeline_config=pipeline_config,
    )
    task = task_crud.create(db, task)

    logger.info("Task %s created for novel %s", task.id, novel_id)
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
def update_task_status(task_id: str, body: dict, db: Session = Depends(get_db)):
    """Update task status with state-machine enforcement.

    Body: ``{"status": str, "progress"?: int, "error_message"?: str}``

    Valid transitions (skip-stage transitions return 422):

    - pending      -> preprocessing | failed
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

    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")

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
    if "progress" in body and isinstance(body["progress"], int):
        updates["progress"] = body["progress"]
    if "error_message" in body:
        updates["error_message"] = body["error_message"]

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
def resume_task(task_id: str, db: Session = Depends(get_db)):
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
