"""Dashboard aggregation endpoint — user-scoped stats and recent items.

GET /api/v1/dashboard returns a single payload combining summary statistics
plus the most recent tasks, scripts, and novels for the authenticated user.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.auth_middleware import get_current_user
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import Novel, Script, Task, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ===================================================================
# GET /api/v1/dashboard
# ===================================================================


@router.get("/")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return user-scoped aggregation stats and recent items.

    Response ``data`` shape::

        {
            "stats": {
                "novels": int,
                "scripts": int,
                "in_progress": int,
                "completed": int,
                "failed": int,
            },
            "recent_tasks": [
                {
                    "task_id": str,
                    "script_id": str | None,
                    "novel_title": str,
                    "status": str,
                    "progress": int,
                    "created_at": str | None,
                },
                ...
            ],
            "recent_scripts": [
                {
                    "script_id": str,
                    "title": str,
                    "source_type": str,
                    "status": str,
                    "scene_count": int,
                    "updated_at": str | None,
                },
                ...
            ],
            "recent_novels": [
                {
                    "id": str,
                    "title": str,
                    "word_count": int,
                    "status": str,
                    "updated_at": str | None,
                },
                ...
            ],
        }
    """
    uid = current_user.id

    # ── stats ────────────────────────────────────────────────────────
    novels_count = db.query(func.count(Novel.id)).filter(
        Novel.user_id == uid
    ).scalar() or 0

    scripts_count = db.query(func.count(Script.id)).filter(
        Script.user_id == uid
    ).scalar() or 0

    in_progress_count = db.query(func.count(Task.id)).filter(
        Task.user_id == uid,
        Task.status.in_(["preprocessing", "converting"]),
    ).scalar() or 0

    completed_count = db.query(func.count(Task.id)).filter(
        Task.user_id == uid,
        Task.status == "completed",
    ).scalar() or 0

    failed_count = db.query(func.count(Task.id)).filter(
        Task.user_id == uid,
        Task.status == "failed",
    ).scalar() or 0

    # ── recent tasks (last 10, newest first) ─────────────────────────
    tasks = (
        db.query(Task, Novel.title.label("novel_title"))
        .join(Novel, Task.novel_id == Novel.id, isouter=True)
        .filter(Task.user_id == uid)
        .order_by(Task.created_at.desc())
        .limit(10)
        .all()
    )

    recent_tasks = [
        {
            "task_id": str(t.Task.id),
            "script_id": str(t.Task.script_id) if t.Task.script_id else None,
            "novel_title": t.novel_title or "",
            "status": t.Task.status,
            "progress": t.Task.progress,
            "created_at": t.Task.created_at.isoformat() if t.Task.created_at else None,
        }
        for t in tasks
    ]

    # ── recent scripts (last 10, newest first) ───────────────────────
    scripts = (
        db.query(Script)
        .filter(Script.user_id == uid)
        .order_by(Script.updated_at.desc())
        .limit(10)
        .all()
    )

    recent_scripts = []
    for s in scripts:
        scene_count = 0
        if s.script_json and isinstance(s.script_json, dict):
            scenes = s.script_json.get("scenes", [])
            if isinstance(scenes, list):
                scene_count = len(scenes)

        recent_scripts.append({
            "script_id": str(s.id),
            "title": s.title,
            "source_type": s.source_type,
            "status": s.status,
            "scene_count": scene_count,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })

    # ── recent novels (last 10, newest first) ────────────────────────
    novels = (
        db.query(Novel)
        .filter(Novel.user_id == uid)
        .order_by(Novel.updated_at.desc())
        .limit(10)
        .all()
    )

    recent_novels = [
        {
            "id": str(n.id),
            "title": n.title,
            "word_count": n.word_count,
            "status": n.status,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        }
        for n in novels
    ]

    return BaseResponse(
        code=200,
        message="Dashboard data retrieved",
        data={
            "stats": {
                "novels": novels_count,
                "scripts": scripts_count,
                "in_progress": in_progress_count,
                "completed": completed_count,
                "failed": failed_count,
            },
            "recent_tasks": recent_tasks,
            "recent_scripts": recent_scripts,
            "recent_novels": recent_novels,
        },
    )
