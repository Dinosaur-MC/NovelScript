"""Script management API — CRUD over Task script fields.

Scripts are stored in the Task model.  Route params use ``script_id``
which transparently maps to a Task primary key.
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

router = APIRouter(prefix="/scripts", tags=["Scripts"])

task_crud = BaseCRUD[Task](Task)


class ScriptUpdateRequest(PydanticBaseModel):
    script_yaml: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_script_id(script_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(script_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid script_id UUID")


def _script_or_404(db: Session, sid: uuid.UUID) -> Task:
    task = task_crud.get(db, sid)
    if task is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return task


def _scene_count(task: Task) -> int:
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
        items.append({
            "script_id": str(task.id),
            "novel_id": str(task.novel_id),
            "status": task.status,
            "progress": task.progress,
            "summary": task.summary,
            "scene_count": _scene_count(task),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        })

    return BaseResponse(code=200, message="ok", data={
        "items": items, "total": total, "page": page, "limit": limit,
    })


# ---------------------------------------------------------------------------
# GET /{script_id}
# ---------------------------------------------------------------------------


@router.get("/{script_id}")
def get_script(script_id: str, db: Session = Depends(get_db)):
    sid = _parse_script_id(script_id)
    task = _script_or_404(db, sid)

    return BaseResponse(code=200, message="ok", data={
        "script_id": str(task.id),
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
    })


# ---------------------------------------------------------------------------
# PUT /{script_id}
# ---------------------------------------------------------------------------


@router.put("/{script_id}")
def update_script(
    script_id: str,
    body: ScriptUpdateRequest,
    db: Session = Depends(get_db),
):
    sid = _parse_script_id(script_id)
    task = _script_or_404(db, sid)

    validation: dict = {"valid": True, "errors": None}
    try:
        yaml.safe_load(body.script_yaml)
    except yaml.YAMLError as exc:
        validation = {"valid": False, "errors": str(exc)}
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")

    task.script_yaml = body.script_yaml
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    db.flush()
    db.refresh(task)

    op = Operation(task_id=sid, type="manual_edit", target_path="/script_yaml")
    db.add(op)
    db.flush()

    return BaseResponse(code=200, message="Script updated", data={
        "script_id": str(task.id),
        "updated_at": task.updated_at.isoformat(),
        "validation": validation,
    })


# ---------------------------------------------------------------------------
# DELETE /{script_id}
# ---------------------------------------------------------------------------


@router.delete("/{script_id}")
def delete_script(script_id: str, db: Session = Depends(get_db)):
    sid = _parse_script_id(script_id)
    success = task_crud.delete(db, sid)
    if not success:
        raise HTTPException(status_code=404, detail="Script not found")
    return BaseResponse(code=200, message="Script deleted", data={"script_id": script_id})


# ---------------------------------------------------------------------------
# GET /{script_id}/export
# ---------------------------------------------------------------------------


@router.get("/{script_id}/export")
def export_script(
    script_id: str,
    format: str = Query("yaml", pattern=r"^(yaml|json|fountain)$"),
    db: Session = Depends(get_db),
):
    sid = _parse_script_id(script_id)
    task = _script_or_404(db, sid)

    if format == "yaml":
        content = task.script_yaml or ""
    elif format == "json":
        content = json_module.dumps(task.script_json or {}, ensure_ascii=False, indent=2)
    else:
        content = task.script_fountain or ""

    return PlainTextResponse(content=content)
