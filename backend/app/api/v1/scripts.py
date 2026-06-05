"""Script management API — CRUD over Task script fields.

Scripts are stored in the Task model; route param is task_id.
"""

from __future__ import annotations

import json as json_module
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import Operation, Task
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scripts", tags=["Scripts"])

task_crud = BaseCRUD[Task](Task)


# ---------------------------------------------------------------------------
# Request body model
# ---------------------------------------------------------------------------


class ScriptUpdateRequest(PydanticBaseModel):
    script_yaml: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_task_id(task_id: str) -> uuid.UUID:
    """Parse task_id string to UUID, raising 422 on failure."""
    try:
        return uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid task_id UUID")


def _task_or_404(db: Session, tid: uuid.UUID) -> Task:
    """Fetch a Task by id, raising 404 if not found."""
    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return task


def _scene_count(task: Task) -> int:
    """Count scenes from script_json."""
    if task.script_json and isinstance(task.script_json, dict):
        scenes = task.script_json.get("scenes", [])
        if isinstance(scenes, list):
            return len(scenes)
    return 0


# ---------------------------------------------------------------------------
# GET / — list scripts
# ---------------------------------------------------------------------------


@router.get("/")
def list_scripts(
    novel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List scripts (tasks) with optional filters.

    Query params: ``novel_id``, ``status``, ``page``, ``limit``.
    Returns scene_count counted from ``script_json.scenes``.
    """
    filters: dict = {}
    if novel_id:
        try:
            filters["novel_id"] = uuid.UUID(novel_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid novel_id UUID")
    if status:
        filters["status"] = status

    offset = (page - 1) * limit
    rows, total = task_crud.list(db, offset=offset, limit=limit, filters=filters)

    items = []
    for task in rows:
        items.append(
            {
                "task_id": str(task.id),
                "novel_id": str(task.novel_id),
                "status": task.status,
                "progress": task.progress,
                "summary": task.summary,
                "scene_count": _scene_count(task),
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        )

    return BaseResponse(
        code=0,
        message="ok",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        },
    )


# ---------------------------------------------------------------------------
# GET /{task_id} — get single script
# ---------------------------------------------------------------------------


@router.get("/{task_id}")
def get_script(task_id: str, db: Session = Depends(get_db)):
    """Return full script data for a task.

    Includes script_yaml, script_json, script_fountain, and characters_json.
    """
    tid = _parse_task_id(task_id)
    task = _task_or_404(db, tid)

    return BaseResponse(
        code=0,
        message="ok",
        data={
            "task_id": str(task.id),
            "novel_id": str(task.novel_id),
            "status": task.status,
            "progress": task.progress,
            "summary": task.summary,
            "script_yaml": task.script_yaml,
            "script_json": task.script_json,
            "script_fountain": task.script_fountain,
            "characters_json": task.characters_json,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        },
    )


# ---------------------------------------------------------------------------
# PUT /{task_id} — update script_yaml
# ---------------------------------------------------------------------------


@router.put("/{task_id}")
def update_script(
    task_id: str,
    body: ScriptUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update script_yaml with YAML validation.

    Validates the YAML is parseable before saving. On save, inserts an
    Operation record (type=manual_edit, target_path=/script_yaml).
    Returns validation info alongside the update confirmation.
    Invalid YAML produces a 422 response.
    """
    tid = _parse_task_id(task_id)
    task = _task_or_404(db, tid)

    # -- YAML validation -------------------------------------------------------
    validation: dict = {"valid": True, "errors": None}
    try:
        yaml.safe_load(body.script_yaml)
    except yaml.YAMLError as exc:
        validation = {"valid": False, "errors": str(exc)}
        raise HTTPException(
            status_code=422,
            detail=f"Invalid YAML: {exc}",
        )

    # -- Save updated script_yaml ----------------------------------------------
    task.script_yaml = body.script_yaml
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    db.flush()
    db.refresh(task)

    # -- Record operation ------------------------------------------------------
    op = Operation(
        task_id=tid,
        type="manual_edit",
        target_path="/script_yaml",
    )
    db.add(op)
    db.flush()

    return BaseResponse(
        code=0,
        message="Script updated",
        data={
            "script_id": str(task.id),
            "updated_at": task.updated_at.isoformat(),
            "validation": validation,
        },
    )


# ---------------------------------------------------------------------------
# DELETE /{task_id} — delete script (task)
# ---------------------------------------------------------------------------


@router.delete("/{task_id}")
def delete_script(task_id: str, db: Session = Depends(get_db)):
    """Delete a script (cascades via FK relationships)."""
    tid = _parse_task_id(task_id)
    success = task_crud.delete(db, tid)
    if not success:
        raise HTTPException(status_code=404, detail="Script not found")

    return BaseResponse(
        code=0,
        message="Script deleted",
        data={"task_id": task_id},
    )


# ---------------------------------------------------------------------------
# GET /{task_id}/export — raw text export
# ---------------------------------------------------------------------------


@router.get("/{task_id}/export")
def export_script(
    task_id: str,
    format: str = Query("yaml", pattern=r"^(yaml|json|fountain)$"),
    db: Session = Depends(get_db),
):
    """Export script as raw text in the requested format.

    ``format`` — one of ``yaml``, ``json``, ``fountain``.
    Returns a plain-text response with the corresponding Task field.
    """
    tid = _parse_task_id(task_id)
    task = _task_or_404(db, tid)

    if format == "yaml":
        content = task.script_yaml or ""
    elif format == "json":
        content = json_module.dumps(
            task.script_json or {}, ensure_ascii=False, indent=2
        )
    else:  # fountain
        content = task.script_fountain or ""

    return PlainTextResponse(content=content)
