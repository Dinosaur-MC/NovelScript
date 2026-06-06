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

from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import Chapter as ChapterModel
from app.models.sql import Novel
from app.services.base import BaseCRUD
from cli.chunker import split_chapters

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
) -> BaseResponse:
    """Core logic: persist a Novel and regex-split Chapters from raw text."""
    # -- Validation -----------------------------------------------------------
    stripped = content.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if len(content.encode("utf-8")) > MAX_CONTENT_SIZE:
        raise HTTPException(status_code=413, detail="Content exceeds 5 MB limit")

    # -- Chapter splitting ----------------------------------------------------
    cli_chapters = split_chapters(stripped)

    # -- Auto-title from first chapter heading --------------------------------
    resolved_title = title
    if not resolved_title and cli_chapters:
        resolved_title = cli_chapters[0].title or "Untitled"
    if not resolved_title:
        resolved_title = "Untitled"

    # -- Persist Novel --------------------------------------------------------
    novel = Novel(
        title=resolved_title,
        author=author,
        source_text=stripped,
        word_count=len(stripped),
        language="zh",
        status="draft",
    )
    novel_crud.create(db, novel)

    # -- Persist Chapters -----------------------------------------------------
    chapter_records: list[ChapterModel] = []
    for cli_ch in cli_chapters:
        ch = ChapterModel(
            novel_id=novel.id,
            chapter_index=cli_ch.index,
            title=cli_ch.title,
            content=cli_ch.text,
        )
        chapter_crud.create(db, ch)
        chapter_records.append(ch)

    logger.info(
        "Novel %s created with %d chapters.", novel.id, len(chapter_records)
    )

    return BaseResponse(
        code=200,
        message="Upload successful",
        data={
            "novel_id": str(novel.id),
            "title": novel.title,
            "chapters": [
                {"index": ch.chapter_index, "title": ch.title}
                for ch in chapter_records
            ],
        },
    )


# ---------------------------------------------------------------------------
# POST /upload — JSON body
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=BaseResponse)
def upload_novel(
    body: UploadRequest,
    db: Session = Depends(get_db),
):
    """Upload novel text as a JSON body — split into chapters via regex."""
    return _create_novel_from_text(body.content, body.title, body.author, db)


# ---------------------------------------------------------------------------
# POST /upload/file — multipart file upload
# ---------------------------------------------------------------------------


@router.post("/upload/file", response_model=BaseResponse)
def upload_novel_file(
    file: UploadFile = File(...),
    title: str = Form("Untitled"),
    author: Optional[str] = Form(None),
    db: Session = Depends(get_db),
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
    return _create_novel_from_text(content, title, author, db)


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
):
    """Update title and/or author of an existing novel."""
    nid = _parse_uuid(novel_id)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = novel_crud.update(db, nid, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Novel not found")

    return BaseResponse(
        code=200,
        message="Updated",
        data={"novel": _serialise_novel(updated)},
    )


# ---------------------------------------------------------------------------
# DELETE /{novel_id} — cascade delete chapters then novel
# ---------------------------------------------------------------------------


@router.delete("/{novel_id}", response_model=BaseResponse)
def delete_novel(novel_id: str, db: Session = Depends(get_db)):
    """Delete a novel and all its chapters (cascade)."""
    nid = _parse_uuid(novel_id)

    novel = novel_crud.get(db, nid)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found")

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
