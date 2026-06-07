"""Pipeline executor helpers — DB cache load/persist for the pipeline.

The Celery task in ``app.tasks.pipeline`` uses these helpers to load
cached chapters/embeddings/KG from the database before running the
pipeline, and to persist them back on first successful completion.

These functions are **not** called from the FastAPI request path —
they run inside the Celery worker process.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from app.core.db import _session_factory
from app.models.sql import (
    Chapter as ChapterModel,
    KnowledgeEdge,
    KnowledgeNode,
    Novel,
    Task,
)
from cli.models import Chapter, KnowledgeEdge as CLIEdge
from cli.models import KnowledgeGraph, KnowledgeNode as CLINode

logger = logging.getLogger(__name__)


def _load_chapters(
    session, novel_id: uuid.UUID,
) -> tuple[list[Chapter] | None, dict[int, list[float]]]:
    """Load DB-stored chapters + cached embeddings for *novel_id*.

    Returns:
        ``(chapters, embeddings_map)`` where *chapters* is ``None`` when
        no rows exist (caller falls back to ``run_from_text``), and
        *embeddings_map* maps ``chapter_index → embedding vector`` (may
        be empty even when chapters are present — meaning embedding hasn't
        been cached yet).
    """
    rows = (
        session.query(ChapterModel)
        .filter(ChapterModel.novel_id == novel_id)
        .order_by(ChapterModel.chapter_index.asc())
        .all()
    )
    if not rows:
        return None, {}

    chapters: list[Chapter] = []
    embeddings_map: dict[int, list[float]] = {}

    for i, r in enumerate(rows):
        chapters.append(Chapter(
            text=r.content or "",
            title=r.title or f"第{i+1}章",
            index=r.chapter_index,
        ))
        if r.embedding is not None and len(r.embedding) > 0:
            embeddings_map[r.chapter_index] = list(r.embedding)

    logger.info(
        "Loaded %d chapter(s) from DB (%d with cached embeddings).",
        len(chapters), len(embeddings_map),
    )
    return chapters, embeddings_map


# ---------------------------------------------------------------------------
# KG cache — load from DB to skip LLM extraction on subsequent runs
# ---------------------------------------------------------------------------


def _load_cached_kg(session, novel_id: uuid.UUID) -> KnowledgeGraph | None:
    """Reconstruct a pipeline ``KnowledgeGraph`` from DB tables.

    Returns ``None`` when no nodes exist for *novel_id* (caller will
    extract via LLM instead).
    """
    nodes = (
        session.query(KnowledgeNode)
        .filter(KnowledgeNode.novel_id == novel_id)
        .all()
    )
    if not nodes:
        return None

    # Build map: DB UUID → CLI string id (n_01, n_02, ...)
    id_map: dict[uuid.UUID, str] = {}
    cli_nodes: list[CLINode] = []
    for i, n in enumerate(nodes):
        cli_id = f"n_{i+1:02d}"
        id_map[n.id] = cli_id
        cli_nodes.append(CLINode(
            id=cli_id,
            name=n.name,
            node_type=n.node_type,
            properties={
                **(n.properties or {}),
                "aliases": n.aliases or [],
                "description": n.description or "",
            },
        ))

    # Load edges for these nodes
    node_uuids = list(id_map.keys())
    if not node_uuids:
        return KnowledgeGraph(nodes=cli_nodes, edges=[])

    db_edges = (
        session.query(KnowledgeEdge)
        .filter(
            KnowledgeEdge.novel_id == novel_id,
            KnowledgeEdge.source_node_id.in_(node_uuids),
            KnowledgeEdge.target_node_id.in_(node_uuids),
        )
        .all()
    )

    cli_edges: list[CLIEdge] = []
    for e in db_edges:
        src = id_map.get(e.source_node_id)
        tgt = id_map.get(e.target_node_id)
        if src and tgt:
            cli_edges.append(CLIEdge(
                source_node_id=src,
                target_node_id=tgt,
                relation=e.relation,
                weight=e.weight or 1.0,
            ))

    kg = KnowledgeGraph(nodes=cli_nodes, edges=cli_edges)
    logger.info(
        "Loaded cached KG from DB: %d node(s), %d edge(s) for novel %s.",
        len(cli_nodes), len(cli_edges), novel_id,
    )
    return kg


# ---------------------------------------------------------------------------
# Chapter persistence — save split results so future runs skip chunking
# ---------------------------------------------------------------------------


def _persist_chapters(
    session,
    novel_id: uuid.UUID,
    summaries: list[str],
) -> None:
    """Insert chapter rows from regex-only split (no LLM, no API call).

    After ``run_from_text`` splits the source text, we persist the
    chapters so the next run can use ``run_from_chapters`` — skipping
    both the chunker AND the summarizer (summaries stored in meta).
    """
    import re

    novel = session.get(Novel, novel_id)
    if novel is None or not (novel.source_text or "").strip():
        return

    text = novel.source_text.strip()
    chapter_re = re.compile(
        r"^\s*第[零一二三四五六七八九十百千\d]+章[^\n]*",
        re.MULTILINE | re.UNICODE,
    )

    positions = [(m.start(), m.end(), m.group().strip()) for m in chapter_re.finditer(text)]
    if not positions:
        # No chapter markers — store as single chapter
        positions = [(0, 0, novel.title or "全文")]

    chapters = _build_chapters_from_positions(text, positions)

    # Delete existing chapters and re-insert
    session.query(ChapterModel).filter(
        ChapterModel.novel_id == novel_id,
    ).delete()
    session.flush()

    for ch in chapters:
        row = ChapterModel(
            novel_id=novel_id,
            chapter_index=ch.index,
            title=ch.title,
            content=ch.text,
        )
        session.add(row)

    logger.info(
        "Persisted %d chapter(s) for novel %s (regex split).", len(chapters), novel_id,
    )


def _build_chapters_from_positions(
    text: str, positions: list[tuple[int, int, str]]
) -> list[Chapter]:
    """Build Chapter objects from regex marker positions (mirrors chunker logic)."""
    chapters: list[Chapter] = []
    for idx, (start, end, title) in enumerate(positions):
        after_header = text.find("\n", end)
        body_start = after_header + 1 if after_header != -1 else end
        body_end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        body = text[body_start:body_end].strip()
        chapters.append(Chapter(text=body, title=title, index=idx))
    return chapters


# ---------------------------------------------------------------------------
# Embedding persistence — cache vectors so future runs skip API calls
# ---------------------------------------------------------------------------


def _persist_embeddings(
    session,
    novel_id: uuid.UUID,
    source_text: str,
    script,
) -> None:
    """Generate and persist per-chapter embeddings to DB.

    Called after the first successful pipeline run.  Future runs load
    these cached vectors via ``_load_chapters`` and build FAISS from
    them without hitting the embedding API.
    """
    from cli.rag_builder import embed_texts

    rows = (
        session.query(ChapterModel)
        .filter(ChapterModel.novel_id == novel_id)
        .order_by(ChapterModel.chapter_index.asc())
        .all()
    )

    if not rows:
        return

    texts = [r.content or "" for r in rows]
    try:
        vectors = embed_texts(texts)
    except Exception:
        logger.exception("Failed to generate embeddings for persistence — will retry next run.")
        return

    for row, vec in zip(rows, vectors):
        if len(vec) != 1536:
            logger.warning(
                "Embedding dimension mismatch for chapter %d: expected 1536, got %d.",
                row.chapter_index, len(vec),
            )
            continue
        row.embedding = vec
        session.add(row)

    session.flush()
    logger.info(
        "Cached %d embedding(s) for novel %s.", len(vectors), novel_id,
    )


def _persist_kg(session, script, task_id: uuid.UUID, novel_id: uuid.UUID, script_id: uuid.UUID | None = None) -> None:
    """Persist CLI KnowledgeGraph nodes/edges to DB tables.

    Maps CLI string ids (``n_01``) → DB UUIDs, inserts nodes first
    then edges referencing those UUIDs.  Skips gracefully when the
    KG is empty.
    """
    kg = script.knowledge_graph
    if not kg.nodes:
        return

    # Map CLI string id → DB UUID
    id_map: dict[str, uuid.UUID] = {}
    db_nodes: list[KnowledgeNode] = []

    for n in kg.nodes:
        db_id = uuid.uuid4()
        id_map[n.id] = db_id
        db_node = KnowledgeNode(
            id=db_id,
            novel_id=novel_id,
            script_id=script_id,
            task_id=task_id,
            node_type=n.node_type,
            name=n.name,
            aliases=n.properties.get("aliases", []),
            description=n.properties.get("description", ""),
            properties=n.properties,
        )
        db_nodes.append(db_node)
        session.add(db_node)

    session.flush()  # populate UUIDs for FK references

    for e in kg.edges:
        src_id = id_map.get(e.source_node_id)
        tgt_id = id_map.get(e.target_node_id)
        if src_id is None or tgt_id is None:
            continue
        db_edge = KnowledgeEdge(
            novel_id=novel_id,
            script_id=script_id,
            task_id=task_id,
            source_node_id=src_id,
            target_node_id=tgt_id,
            relation=e.relation,
            weight=e.weight,
        )
        session.add(db_edge)

    logger.info(
        "Persisted KG: %d node(s), %d edge(s) for task %s.",
        len(db_nodes), len(kg.edges), task_id,
    )


def _fail(session, task_id: uuid.UUID, message: str) -> None:
    """Set *task_id* to ``failed`` with *message*."""
    try:
        task = session.get(Task, task_id)
        if task is not None:
            task.status = "failed"
            task.error_message = message[:5000]  # guard against huge tracebacks
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
    except Exception:
        logger.exception("Failed to persist failure for task %s.", task_id)
        session.rollback()


def recover_stale_tasks() -> int:
    """Mark in-flight tasks as ``failed`` after a full system restart.

    Celery workers are separate processes — they survive FastAPI restarts
    just fine.  But if Redis is flushed or the entire machine reboots,
    tasks left in ``preprocessing`` or ``converting`` are orphaned.
    This function moves them to ``failed`` so users can resume them
    manually.

    Returns the number of tasks recovered.
    """
    session = _session_factory()
    try:
        from sqlalchemy import update

        now = datetime.now(timezone.utc)
        stale_msg = "Server restarted — pipeline interrupted. Use /resume to retry."
        result = session.execute(
            update(Task)
            .where(Task.status.in_(["preprocessing", "converting"]))
            .values(status="failed", error_message=stale_msg, updated_at=now)
        )
        session.commit()
        count = result.rowcount
        if count:
            logger.warning("Recovered %d stale task(s) after server restart.", count)
        return count
    except Exception:
        session.rollback()
        logger.exception("Failed to recover stale tasks.")
        return 0
    finally:
        session.close()
