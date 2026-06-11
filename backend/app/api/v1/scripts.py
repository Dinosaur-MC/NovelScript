"""Script management API — full CRUD over the first-class Script entity.

Scripts can be:
  - **generated**  — created by the pipeline from a Novel
  - **forked**     — cloned from a generated Script for independent editing
  - **standalone** — created directly (no Novel source)
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
from pydantic import BaseModel as PydanticBaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import (
    Chapter,
    Dialogue,
    KnowledgeEdge,
    KnowledgeNode,
    Novel,
    Operation,
    Script,
    User,
)
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scripts", tags=["Scripts"])

script_crud = BaseCRUD[Script](Script)
novel_crud = BaseCRUD[Novel](Novel)


# ── Request models ──────────────────────────────────────────────────

class CreateScriptRequest(PydanticBaseModel):
    title: str = Field("Untitled Script", max_length=500)
    source_type: str = Field("standalone", pattern=r"^(standalone|forked)$")
    novel_id: Optional[str] = Field(None, description="Ref if forked from a novel")
    fork_from_id: Optional[str] = Field(None, description="Script UUID to fork")


class UpdateScriptRequest(PydanticBaseModel):
    script_yaml: str


# ── Helpers ─────────────────────────────────────────────────────────

def _parse_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID")


def _scene_count(script: Optional[Script]) -> int:
    if script and script.script_json and isinstance(script.script_json, dict):
        scenes = script.script_json.get("scenes", [])
        if isinstance(scenes, list):
            return len(scenes)
    return 0


# ── GET / — list scripts of current user ────────────────────────────

@router.get("/")
def list_scripts(
    novel_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List scripts — optionally filtered by novel, status, or source type."""
    stmt = select(Script).order_by(Script.updated_at.desc())
    if novel_id:
        stmt = stmt.where(Script.novel_id == _parse_id(novel_id))
    if status:
        stmt = stmt.where(Script.status == status)
    if source_type:
        stmt = stmt.where(Script.source_type == source_type)

    count_stmt = select(func.count(Script.id))
    if novel_id:
        count_stmt = count_stmt.where(Script.novel_id == _parse_id(novel_id))
    if status:
        count_stmt = count_stmt.where(Script.status == status)
    if source_type:
        count_stmt = count_stmt.where(Script.source_type == source_type)
    total = db.execute(count_stmt).scalar() or 0
    offset = (page - 1) * limit
    rows = db.execute(stmt.offset(offset).limit(limit)).scalars().all()

    items = [
        {
            "script_id": str(s.id),
            "novel_id": str(s.novel_id) if s.novel_id else None,
            "title": s.title,
            "source_type": s.source_type,
            "status": s.status,
            "summary": s.summary,
            "scene_count": _scene_count(s),
            "progress": 100,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in rows
    ]
    return BaseResponse(code=200, message="ok", data={
        "items": items, "total": total, "page": page, "limit": limit,
    })


# ── POST / — create standalone or forked script ─────────────────────

@router.post("/")
def create_script(
    body: CreateScriptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new standalone script or fork an existing one."""
    nid: Optional[uuid.UUID] = None
    fork_src: Optional[Script] = None

    if body.novel_id:
        nid = _parse_id(body.novel_id)

    if body.fork_from_id:
        fork_id = _parse_id(body.fork_from_id)
        fork_src = script_crud.get(db, fork_id)
        if fork_src is None:
            raise HTTPException(status_code=404, detail="Source script not found")

    script = Script(
        user_id=current_user.id,
        novel_id=nid,
        title=body.title,
        source_type=body.source_type,
        status="draft",
    )

    if fork_src:
        script.novel_id = fork_src.novel_id
        script.script_yaml = fork_src.script_yaml
        script.script_json = fork_src.script_json
        script.script_fountain = fork_src.script_fountain
        script.characters_json = fork_src.characters_json
        script.summary = fork_src.summary
        script.source_type = "forked"

    script_crud.create(db, script)

    return BaseResponse(code=201, message="Script created", data={
        "script_id": str(script.id),
        "title": script.title,
        "source_type": script.source_type,
    })


# ── GET /{script_id} — detail ───────────────────────────────────────

@router.get("/{script_id}")
def get_script(
    script_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a script with full artifacts and knowledge graph."""
    sid = _parse_id(script_id)
    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")

    # Load script-level KG
    kg_nodes = db.execute(
        select(KnowledgeNode).where(KnowledgeNode.script_id == sid)
    ).scalars().all()
    kg_edges = db.execute(
        select(KnowledgeEdge).where(KnowledgeEdge.script_id == sid)
    ).scalars().all()

    return BaseResponse(code=200, message="ok", data={
        "script_id": str(script.id),
        "novel_id": str(script.novel_id) if script.novel_id else None,
        "user_id": str(script.user_id) if script.user_id else None,
        "title": script.title,
        "source_type": script.source_type,
        "status": script.status,
        "summary": script.summary,
        "script_yaml": script.script_yaml,
        "script_json": script.script_json,
        "script_fountain": script.script_fountain,
        "characters_json": script.characters_json,
        "knowledge_graph": {
            "nodes": [
                {
                    "id": str(n.id), "node_type": n.node_type, "name": n.name,
                    "aliases": n.aliases, "description": n.description,
                    "properties": n.properties,
                }
                for n in kg_nodes
            ],
            "edges": [
                {
                    "id": str(e.id),
                    "source_node_id": str(e.source_node_id),
                    "target_node_id": str(e.target_node_id),
                    "relation": e.relation, "weight": e.weight,
                }
                for e in kg_edges
            ],
        },
        "created_at": script.created_at.isoformat() if script.created_at else None,
        "updated_at": script.updated_at.isoformat() if script.updated_at else None,
    })


# ── PUT /{script_id} — save YAML edits ──────────────────────────────

@router.put("/{script_id}")
def update_script(
    script_id: str,
    body: UpdateScriptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save YAML content. Validates syntax before persisting."""
    sid = _parse_id(script_id)
    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    require_ownership(script, current_user, resource_name="剧本", action="编辑")

    validation: dict = {"valid": True, "errors": None}
    try:
        yaml.safe_load(body.script_yaml)
    except yaml.YAMLError as exc:
        validation = {"valid": False, "errors": str(exc)}
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}")

    script.script_yaml = body.script_yaml
    script.updated_at = datetime.now(timezone.utc)
    db.add(script)
    db.flush()

    op = Operation(
        script_id=sid,
        task_id=None,
        user_id=current_user.id,
        type="manual_edit",
        target_path="/script_yaml",
    )
    db.add(op)
    db.flush()

    return BaseResponse(code=200, message="Script updated", data={
        "script_id": str(script.id),
        "updated_at": script.updated_at.isoformat(),
        "validation": validation,
    })


# ── DELETE /{script_id} ─────────────────────────────────────────────

@router.delete("/{script_id}")
def delete_script(
    script_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete script, cascading dialogues, operations, and KG edges."""
    sid = _parse_id(script_id)
    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    require_ownership(script, current_user, resource_name="剧本", action="删除")

    # Cascade-delete edges referencing nodes owned by this script
    node_ids = [
        r[0] for r in db.execute(
            select(KnowledgeNode.id).where(KnowledgeNode.script_id == sid)
        ).all()
    ]
    if node_ids:
        db.execute(
            select(KnowledgeEdge).where(
                (KnowledgeEdge.source_node_id.in_(node_ids))
                | (KnowledgeEdge.target_node_id.in_(node_ids))
            )
        )
        # Delete edges
        from sqlalchemy import delete as sa_delete
        db.execute(sa_delete(KnowledgeEdge).where(
            (KnowledgeEdge.source_node_id.in_(node_ids))
            | (KnowledgeEdge.target_node_id.in_(node_ids))
        ))
        # Delete nodes
        db.execute(sa_delete(KnowledgeNode).where(KnowledgeNode.script_id == sid))
        # Delete dialogues
        db.execute(sa_delete(Dialogue).where(Dialogue.script_id == sid))
        # Delete operations
        db.execute(sa_delete(Operation).where(Operation.script_id == sid))

    script_crud.delete(db, sid)
    return BaseResponse(code=200, message="Script deleted", data={"script_id": script_id})


# ── POST /{script_id}/fork ──────────────────────────────────────────

@router.post("/{script_id}/fork")
def fork_script(
    script_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clone a script into a standalone, editable copy."""
    sid = _parse_id(script_id)
    src = script_crud.get(db, sid)
    if src is None:
        raise HTTPException(status_code=404, detail="Source script not found")
    require_ownership(src, current_user, resource_name="剧本", action="复制")

    fork = Script(
        user_id=current_user.id,
        novel_id=src.novel_id,
        title=f"{src.title} (副本)",
        source_type="forked",
        status="draft",
        script_yaml=src.script_yaml,
        script_json=src.script_json,
        script_fountain=src.script_fountain,
        characters_json=src.characters_json,
        summary=src.summary,
        token_usage=src.token_usage,
    )
    script_crud.create(db, fork)

    return BaseResponse(code=201, message="Script forked", data={
        "script_id": str(fork.id),
        "title": fork.title,
    })


# ── GET /{script_id}/export ─────────────────────────────────────────

@router.get("/{script_id}/export")
def export_script(
    script_id: str,
    format: str = Query("yaml", pattern=r"^(yaml|json|fountain)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export script in the requested format."""
    sid = _parse_id(script_id)
    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")

    if format == "yaml":
        content = script.script_yaml or ""
    elif format == "json":
        content = json_module.dumps(script.script_json or {}, ensure_ascii=False, indent=2)
    else:
        content = script.script_fountain or ""
    return PlainTextResponse(content=content)


# ── GET /{script_id}/dialogues ──────────────────────────────────────

@router.get("/{script_id}/dialogues")
def list_dialogues(
    script_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve AI chat history for a script."""
    sid = _parse_id(script_id)
    rows = db.execute(
        select(Dialogue)
        .where(Dialogue.script_id == sid)
        .order_by(Dialogue.created_at.asc())
    ).scalars().all()

    return BaseResponse(code=200, message="ok", data={
        "dialogues": [
            {
                "id": str(d.id), "role": d.role, "content": d.content,
                "patch_json": d.patch_json, "created_at": d.created_at.isoformat(),
            }
            for d in rows
        ]
    })
