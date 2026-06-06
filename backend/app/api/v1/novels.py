"""Novel Management API — upload, list, detail, update, delete.

Agent D: Novel Management — fully synchronous, no async/await.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlmodel import select

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import Chapter as ChapterModel
from app.models.sql import Novel, Task, User
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/novels", tags=["Novels"])

novel_crud = BaseCRUD[Novel](Novel)
chapter_crud = BaseCRUD[ChapterModel](ChapterModel)

MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5 MB


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class UploadRequest(BaseModel):
    """JSON body for novel text upload."""

    content: str = Field(..., description="Full novel text")
    title: Optional[str] = Field(None, max_length=500, description="Novel title")
    author: Optional[str] = Field(None, max_length=300, description="Author name")


class UpdateRequest(BaseModel):
    """Fields that can be updated on an existing novel."""

    title: Optional[str] = Field(None, max_length=500, description="New title")
    author: Optional[str] = Field(None, max_length=300, description="New author")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _create_novel_from_text(
    content: str,
    title: Optional[str],
    author: Optional[str],
    db: Session,
    *,
    user_id: uuid.UUID,
    auto_convert: bool = True,
) -> BaseResponse:
    """Core logic: persist a Novel and optionally start a conversion Task.

    Chapter splitting is deferred to the background pipeline thread so the
    upload response returns immediately (no blocking LLM call).  When
    *auto_convert* is True (the default), a Task is created and the
    pipeline is spawned in a background daemon thread.  The response
    includes ``task_id`` so the frontend can immediately subscribe to SSE
    progress events without a second API call.
    """
    # -- Validation -----------------------------------------------------------
    stripped = content.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if len(content.encode("utf-8")) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Content exceeds 5 MB limit")

    # -- Auto-title -----------------------------------------------------------
    resolved_title = title
    if not resolved_title:
        # Quick regex scan for the first chapter heading (no LLM — fast)
        import re
        m = re.search(r"第[零一二三四五六七八九十百千\d]+章\s*[^\n]*", stripped)
        resolved_title = m.group().strip() if m else "Untitled"
    if not resolved_title:
        resolved_title = "Untitled"

    # -- Persist Novel --------------------------------------------------------
    novel = Novel(
        user_id=user_id,
        title=resolved_title,
        author=author,
        source_text=stripped,
        word_count=len(stripped),
        language="zh",
        status="draft",
    )
    novel_crud.create(db, novel)

    logger.info("Novel %s created (%d chars).", novel.id, len(stripped))

    # -- Response payload (chapters empty — deferred to pipeline) --------------
    data: dict = {
        "novel_id": str(novel.id),
        "title": novel.title,
        "chapters": [],
    }

    # -- Auto-create Task & dispatch to Celery worker -------------------
    if auto_convert:
        task = Task(
            novel_id=novel.id,
            user_id=user_id,
            status="pending",
            progress=0,
        )
        db.add(task)
        db.flush()
        db.commit()

        data["task_id"] = str(task.id)
        data["task_status"] = task.status

        from app.tasks.pipeline import run_pipeline

        run_pipeline.apply_async(
            args=(str(task.id), str(novel.id)),
            task_id=str(task.id),
        )
    else:
        db.commit()

    return BaseResponse(
        code=200,
        message="Upload successful",
        data=data,
    )


# ---------------------------------------------------------------------------
# POST /upload — JSON body
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=BaseResponse)
def upload_novel(
    body: UploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload novel text as a JSON body — split into chapters via regex."""
    return _create_novel_from_text(body.content, body.title, body.author, db, user_id=current_user.id)


# ---------------------------------------------------------------------------
# POST /upload/file — multipart file upload
# ---------------------------------------------------------------------------


@router.post("/upload/file", response_model=BaseResponse)
def upload_novel_file(
    file: UploadFile = File(...),
    title: str = Form("Untitled"),
    author: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload novel text as a multipart file — split into chapters via regex.

    Accepts UTF-8 encoded files.  Falls back to common CJK encodings
    (GBK, GB2312, GB18030) if UTF-8 decoding fails, since Chinese
    novels are often authored on Windows with legacy encodings.
    """
    raw = file.file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Try common CJK encodings
        for enc in ("gb18030", "gbk", "gb2312", "big5"):
            try:
                content = raw.decode(enc)
                logger.info("Uploaded file decoded as %s (not UTF-8).", enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(
                status_code=400,
                detail="Could not decode file — expected UTF-8 or GBK encoding.",
            )
    return _create_novel_from_text(content, title, author, db, user_id=current_user.id)


# ---------------------------------------------------------------------------
# GET / — list novels (paginated)
# ---------------------------------------------------------------------------


@router.get("/", response_model=BaseResponse)
def list_novels(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """List novels with pagination."""
    offset = (page - 1) * limit
    items, total = novel_crud.list(db, offset=offset, limit=limit)

    return BaseResponse(
        code=200,
        message="OK",
        data={
            "total": total,
            "items": [_serialise_novel(item) for item in items],
        },
    )


# ---------------------------------------------------------------------------
# GET /{novel_id} — detail with nested chapters
# ---------------------------------------------------------------------------


@router.get("/{novel_id}", response_model=BaseResponse)
def get_novel(novel_id: str, db: Session = Depends(get_db)):
    """Get a single novel with its ordered chapters nested in the response."""
    nid = _parse_uuid(novel_id)
    novel = novel_crud.get(db, nid)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")

    stmt = (
        select(ChapterModel)
        .where(ChapterModel.novel_id == nid)
        .order_by(ChapterModel.chapter_index.asc())
    )
    chapters = db.execute(stmt).scalars().all()

    return BaseResponse(
        code=200,
        message="OK",
        data={
            "novel": _serialise_novel(novel),
            "chapters": [_serialise_chapter(ch) for ch in chapters],
        },
    )


# ---------------------------------------------------------------------------
# PUT /{novel_id} — update title / author
# ---------------------------------------------------------------------------


@router.put("/{novel_id}", response_model=BaseResponse)
def update_novel(
    novel_id: str,
    body: UpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update title and/or author of an existing novel."""
    nid = _parse_uuid(novel_id)
    novel = novel_crud.get(db, nid)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")
    require_ownership(novel, current_user, resource_name="小说", action="修改")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = novel_crud.update(db, nid, updates)

    return BaseResponse(
        code=200,
        message="Updated",
        data={"novel": _serialise_novel(updated)},
    )


# ---------------------------------------------------------------------------
# DELETE /{novel_id} — cascade delete chapters then novel
# ---------------------------------------------------------------------------


@router.delete("/{novel_id}", response_model=BaseResponse)
def delete_novel(
    novel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a novel and all its chapters (cascade)."""
    nid = _parse_uuid(novel_id)

    novel = novel_crud.get(db, nid)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")
    require_ownership(novel, current_user, resource_name="小说", action="删除")

    # Cascade-delete chapters manually (FK lacks ON DELETE CASCADE)
    stmt = select(ChapterModel).where(ChapterModel.novel_id == nid)
    chapters = db.execute(stmt).scalars().all()
    for ch in chapters:
        db.delete(ch)
    db.flush()

    novel_crud.delete(db, nid)

    return BaseResponse(
        code=200,
        message="Deleted",
        data={"deleted_id": str(nid)},
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_uuid(raw: str) -> uuid.UUID:
    """Parse a string to UUID, raising 422 on invalid input."""
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {raw}")


def _serialise_novel(obj: Novel, *, include_source: bool = False) -> dict:
    """Convert a Novel ORM instance to a JSON-safe dict.

    Set ``include_source=True`` for the detail endpoint; the list endpoint
    should not transfer the full ``source_text`` for every novel.
    """
    data = obj.model_dump(mode="json")
    if not include_source:
        data.pop("source_text", None)
        data.pop("meta", None)
    return data


def _serialise_chapter(obj: ChapterModel) -> dict:
    """Convert a Chapter ORM instance to a JSON-safe dict."""
    return obj.model_dump(mode="json")
