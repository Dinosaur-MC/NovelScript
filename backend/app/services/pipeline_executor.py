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


# Map from node_type to ID prefix for CLI-compatible identifiers
_TYPE_PREFIX: dict[str, str] = {
    "character":    "char",
    "location":     "loc",
    "item":         "item",
    "event":        "event",
    "organization": "org",
}


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

    # Build map: DB UUID → CLI string id with type-specific prefix
    # (char_01, loc_01, item_01, event_01, org_01, ...)
    id_map: dict[uuid.UUID, str] = {}
    cli_nodes: list[CLINode] = []
    _counters: dict[str, int] = {}
    for n in nodes:
        prefix = _TYPE_PREFIX.get(n.node_type, "node")
        idx = _counters.get(prefix, 0) + 1
        _counters[prefix] = idx
        cli_id = f"{prefix}_{idx:02d}"
        id_map[n.id] = cli_id
        cli_nodes.append(CLINode(
            id=cli_id,
            label=n.name,
            type=n.node_type,
            metadata={
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
                source=src,
                target=tgt,
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

    Maps CLI string ids (``char_01``) → DB UUIDs, inserts nodes first
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
            node_type=n.type,
            name=n.label,
            aliases=n.metadata.get("aliases", []),
            description=n.metadata.get("description", ""),
            properties=n.metadata,
        )
        db_nodes.append(db_node)
        session.add(db_node)

    session.flush()  # populate UUIDs for FK references

    for e in kg.edges:
        src_id = id_map.get(e.source)
        tgt_id = id_map.get(e.target)
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


def _safe_get(data: object, key: str, default: object = None) -> object:
    """Get attribute or dict key from *data*, returning *default* on missing."""
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def persist_pipeline_output(
    session,
    output,
    task_id: uuid.UUID,
    novel_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> str | None:
    """Persist a PipelineOutput to the database.

    Creates/updates the Task and Script records, persisting chapters,
    embeddings, KG nodes/edges.

    Returns the Script ID if a Script was created, else None.
    This function is called by the Main process (FastAPI), NOT by Celery.
    """
    from app.models.sql import Script as ScriptModel

    data = output if hasattr(output, "to_dict") else output
    status = getattr(data, "status", "failed")
    script_id: str | None = None

    try:
        # ── Update Task ────────────────────────────────────────────────
        task = session.get(Task, task_id)
        if task is None:
            logger.error("Task %s not found in DB — cannot persist output.", task_id)
            return None

        if status == "completed":
            task.status = "completed"
            task.progress = 100
            task.summary = getattr(data, "summary", "")
            # Prefer PipelineOutput's own script_yaml/script_json (always correct)
            # Only rebuild via _build_script_obj as a fallback when they're missing
            pipeline_yaml = _safe_get(data, "script_yaml", "")
            pipeline_json = _safe_get(data, "script_json", None)
            pipeline_fountain = _safe_get(data, "script_fountain", "")

            if pipeline_yaml:
                task.script_yaml = pipeline_yaml
                task.script_json = pipeline_json or _safe_get(data, "script_json", {})
                task.script_fountain = pipeline_fountain
            else:
                # Legacy: rebuild from PipelineOutput fields
                from cli.exporter import to_yaml
                script_obj = _build_script_obj(data)
                if script_obj:
                    task.script_yaml = to_yaml(script_obj)
                    task.script_json = script_obj.model_dump(mode="json") if hasattr(script_obj, "model_dump") else {}
                    from cli.fountain_exporter import to_fountain
                    task.script_fountain = to_fountain(script_obj)
                else:
                    task.script_yaml = ""
                    task.script_json = {}
                    task.script_fountain = ""
            task.characters_json = getattr(data, "characters", [])
            task.token_usage = getattr(data, "token_usage", {})
            task.error_message = None
        else:
            task.status = "failed"
            task.error_message = getattr(data, "error_message", "Pipeline failed")[:5000]

        task.updated_at = datetime.now(timezone.utc)
        session.add(task)

        # ── Create/Update Script ───────────────────────────────────────
        if status == "completed":
            if task.script_id:
                script_row = session.get(ScriptModel, task.script_id)
            else:
                script_row = None

            if script_row is None:
                script_row = ScriptModel(
                    novel_id=novel_id,
                    user_id=user_id or task.user_id,
                    title=task.summary or "Generated Script",
                    source_type="generated",
                )
                session.add(script_row)
                session.flush()
                task.script_id = script_row.id
                session.add(task)

            script_row.script_yaml = task.script_yaml
            script_row.script_json = task.script_json
            script_row.script_fountain = task.script_fountain
            script_row.token_usage = task.token_usage
            script_row.characters_json = task.characters_json
            script_row.summary = task.summary
            script_row.status = "completed"
            script_row.updated_at = datetime.now(timezone.utc)
            session.add(script_row)

            script_id = str(script_row.id) if script_row else None

        # ── Commit main result ─────────────────────────────────────────
        session.commit()
        logger.info("Pipeline output persisted for task %s (script_id=%s).", task_id, script_id)

        # ── Chapters, embeddings, KG (best-effort, independent txn) ────
        try:
            chapters_data = getattr(data, "chapters", [])
            if chapters_data:
                _persist_chapters_from_dto(session, novel_id, chapters_data)

            embeddings_map = getattr(data, "embeddings_map", {})
            if embeddings_map:
                _persist_embeddings_from_dto(session, novel_id, embeddings_map)

            kg = getattr(data, "knowledge_graph", None)
            if kg and getattr(kg, "nodes", []):
                _persist_kg_from_dto(session, kg, task_id, novel_id, script_id)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Cache persistence failed (non-critical).")

        return script_id

    except Exception:
        session.rollback()
        logger.exception("Failed to persist pipeline output for task %s.", task_id)
        return None


def _build_script_obj(data):
    """Reconstruct a CLI Script object from PipelineOutput data."""
    try:
        from cli.models import Script as CLIScript, Scene, Character, KnowledgeGraph, KnowledgeNode as CLINode, KnowledgeEdge as CLIEdge

        scenes_data = getattr(data, "scenes", []) or data.get("scenes", []) if isinstance(data, dict) else []
        characters_data = getattr(data, "characters", []) or data.get("characters", []) if isinstance(data, dict) else []
        summary = getattr(data, "summary", "") or data.get("summary", "") if isinstance(data, dict) else ""
        token_usage = getattr(data, "token_usage", {}) or data.get("token_usage", {}) if isinstance(data, dict) else {}

        scenes = [Scene(**s) if isinstance(s, dict) else s for s in scenes_data]
        characters = [Character(**c) if isinstance(c, dict) else Character(id=c.get("id",""), name=c.get("name","")) for c in characters_data]

        # KG
        kg_data = getattr(data, "knowledge_graph", None) or (data.get("knowledge_graph") if isinstance(data, dict) else None)
        kg = None
        if kg_data:
            nodes_data = getattr(kg_data, "nodes", []) or kg_data.get("nodes", []) if isinstance(kg_data, dict) else []
            edges_data = getattr(kg_data, "edges", []) or kg_data.get("edges", []) if isinstance(kg_data, dict) else []
            nodes = [
                CLINode(id=n["id"] if isinstance(n, dict) else n.id, label=n["label"] if isinstance(n, dict) else n.label, type=n["type"] if isinstance(n, dict) else n.type, metadata=n.get("metadata", {}) if isinstance(n, dict) else n.metadata)
                for n in nodes_data
            ]
            edges = [
                CLIEdge(source=e["source"] if isinstance(e, dict) else e.source, target=e["target"] if isinstance(e, dict) else e.target, relation=e.get("relation", "") if isinstance(e, dict) else e.relation, weight=e.get("weight", 1.0) if isinstance(e, dict) else e.weight)
                for e in edges_data
            ]
            kg = KnowledgeGraph(nodes=nodes, edges=edges)

        cli_script = CLIScript(
            scenes=scenes,
            characters=characters,
            summary=summary,
            knowledge_graph=kg or KnowledgeGraph(),
            meta={"usage": token_usage},
        )
        return cli_script
    except Exception:
        logger.exception("Failed to build script object from PipelineOutput.")
        return None


def _persist_chapters_from_dto(session, novel_id: uuid.UUID, chapters_data: list) -> None:
    """Persist chapters from PipelineOutput chapter list."""
    from app.models.sql import Chapter as ChapterModel

    session.query(ChapterModel).filter(ChapterModel.novel_id == novel_id).delete()
    session.flush()

    for ch in chapters_data:
        index = ch.index if hasattr(ch, "index") else ch["index"]
        title = ch.title if hasattr(ch, "title") else ch.get("title", "")
        text = ch.text if hasattr(ch, "text") else ch.get("text", "")
        row = ChapterModel(novel_id=novel_id, chapter_index=index, title=title, content=text)
        session.add(row)

    logger.info("Persisted %d chapter(s) from pipeline output.", len(chapters_data))


def _chunk_and_persist_chapters(session, novel_id: uuid.UUID, source_text: str) -> int:
    """Split *source_text* into chapters (regex, no LLM) and persist to DB.

    Used during novel upload so the reader always has chapters to display,
    even before the first pipeline run.  Returns the number of chapters created.
    """
    from cli.chunker import split_chapters
    from app.models.sql import Chapter as ChapterModel

    chunks = split_chapters(source_text)
    if not chunks:
        return 0

    session.query(ChapterModel).filter(ChapterModel.novel_id == novel_id).delete()
    session.flush()

    for ch in chunks:
        row = ChapterModel(
            novel_id=novel_id, chapter_index=ch.index,
            title=ch.title, content=ch.text,
        )
        session.add(row)
    session.commit()
    logger.info("Chunked and persisted %d chapter(s) for novel %s.", len(chunks), novel_id)
    return len(chunks)


def _persist_embeddings_from_dto(session, novel_id: uuid.UUID, embeddings_map: dict[int, list[float]]) -> None:
    """Persist chapter embeddings from pipeline output."""
    from app.models.sql import Chapter as ChapterModel

    rows = (
        session.query(ChapterModel)
        .filter(ChapterModel.novel_id == novel_id)
        .order_by(ChapterModel.chapter_index.asc())
        .all()
    )
    for row in rows:
        vec = embeddings_map.get(row.chapter_index)
        if vec and len(vec) == 1536:
            row.embedding = vec
            session.add(row)

    logger.info("Persisted %d embedding(s) from pipeline output.", len(embeddings_map))


def _persist_kg_from_dto(session, kg, task_id: uuid.UUID, novel_id: uuid.UUID, script_id_str: str | None = None) -> None:
    """Persist KG nodes/edges from PipelineOutput knowledge_graph."""
    from app.models.sql import KnowledgeNode, KnowledgeEdge

    nodes_data = kg.nodes if hasattr(kg, "nodes") else kg.get("nodes", [])
    edges_data = kg.edges if hasattr(kg, "edges") else kg.get("edges", [])

    if not nodes_data:
        return

    script_uuid = uuid.UUID(script_id_str) if script_id_str else None
    id_map: dict[str, uuid.UUID] = {}

    for n in nodes_data:
        nid = n.id if hasattr(n, "id") else n["id"]
        label = n.label if hasattr(n, "label") else n["label"]
        ntype = n.type if hasattr(n, "type") else n["type"]
        metadata = n.metadata if hasattr(n, "metadata") else n.get("metadata", {})

        db_id = uuid.uuid4()
        id_map[nid] = db_id
        db_node = KnowledgeNode(
            id=db_id, novel_id=novel_id, script_id=script_uuid, task_id=task_id,
            node_type=ntype, name=label,
            aliases=metadata.get("aliases", []),
            description=metadata.get("description", ""),
            properties=metadata,
        )
        session.add(db_node)

    session.flush()

    for e in edges_data:
        src = e.source if hasattr(e, "source") else e["source"]
        tgt = e.target if hasattr(e, "target") else e["target"]
        rel = e.relation if hasattr(e, "relation") else e.get("relation", "")
        wgt = e.weight if hasattr(e, "weight") else e.get("weight", 1.0)

        src_id = id_map.get(src)
        tgt_id = id_map.get(tgt)
        if src_id and tgt_id:
            db_edge = KnowledgeEdge(
                novel_id=novel_id, script_id=script_uuid, task_id=task_id,
                source_node_id=src_id, target_node_id=tgt_id,
                relation=rel, weight=wgt,
            )
            session.add(db_edge)

    logger.info("Persisted KG: %d node(s), %d edge(s).", len(nodes_data), len(edges_data))


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
