"""Pipeline Data Transfer Objects — serializable payloads for Celery communication.

Refactored data flow::

  DB → Main (FastAPI) → Redis payload → Celery worker → Redis result → Main → DB

Celery workers NEVER touch the database directly.  All novel data is
serialized into a :class:`PipelineInput` object by the API layer, stored
in Redis with a short TTL, and passed to the worker.  Results are
returned as a :class:`PipelineOutput` object via Celery's result backend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types (plain dicts — JSON-safe for Redis transport)
# ---------------------------------------------------------------------------


@dataclass
class ChapterData:
    """Serializable chapter — mirrors cli.models.Chapter."""
    index: int
    title: str
    text: str
    embedding: list[float] | None = None


@dataclass
class KGNodeData:
    """Serializable knowledge graph node."""
    id: str
    label: str
    type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KGEdgeData:
    """Serializable knowledge graph edge."""
    source: str
    target: str
    relation: str = ""
    weight: float = 1.0


@dataclass
class KnowledgeGraphData:
    """Serializable knowledge graph (without ORM references)."""
    nodes: list[KGNodeData] = field(default_factory=list)
    edges: list[KGEdgeData] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline I/O DTOs
# ---------------------------------------------------------------------------


@dataclass
class PipelineInput:
    """Everything the Celery worker needs — no DB session required.

    Serialized to JSON and stored in Redis before dispatch.
    """
    task_id: str
    novel_id: str
    source_text: str = ""
    novel_title: str = ""
    style_direction: str = ""
    chapters: list[ChapterData] = field(default_factory=list)
    embeddings_map: dict[int, list[float]] = field(default_factory=dict)
    cached_kg: KnowledgeGraphData | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineInput":
        chapters = [ChapterData(**ch) for ch in data.get("chapters", [])]
        kg_data = data.get("cached_kg")
        cached_kg = KnowledgeGraphData(
            nodes=[KGNodeData(**n) for n in kg_data["nodes"]] if kg_data and kg_data.get("nodes") else [],
            edges=[KGEdgeData(**e) for e in kg_data["edges"]] if kg_data and kg_data.get("edges") else [],
        ) if kg_data else None
        return cls(
            task_id=data["task_id"],
            novel_id=data["novel_id"],
            source_text=data.get("source_text", ""),
            novel_title=data.get("novel_title", ""),
            style_direction=data.get("style_direction", ""),
            chapters=chapters,
            embeddings_map={int(k): v for k, v in data.get("embeddings_map", {}).items()},
            cached_kg=cached_kg,
        )


@dataclass
class PipelineOutput:
    """Pipeline execution result — passed back through Celery result backend.

    Main (FastAPI) is responsible for persisting these to the database.
    """
    status: str
    scenes: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    script_yaml: str = ""
    script_json: dict[str, Any] = field(default_factory=dict)
    script_fountain: str = ""
    characters: list[dict[str, Any]] = field(default_factory=list)
    chapters: list[ChapterData] = field(default_factory=list)
    embeddings_map: dict[int, list[float]] = field(default_factory=dict)
    knowledge_graph: KnowledgeGraphData | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.knowledge_graph:
            d["knowledge_graph"] = self.knowledge_graph.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineOutput":
        kg_data = data.get("knowledge_graph")
        kg = KnowledgeGraphData(
            nodes=[KGNodeData(**n) for n in kg_data["nodes"]] if kg_data and kg_data.get("nodes") else [],
            edges=[KGEdgeData(**e) for e in kg_data["edges"]] if kg_data and kg_data.get("edges") else [],
        ) if kg_data else None
        chapters = [ChapterData(**ch) for ch in data.get("chapters", [])]
        return cls(
            status=data.get("status", "failed"),
            scenes=data.get("scenes", []),
            summary=data.get("summary", ""),
            script_yaml=data.get("script_yaml", ""),
            script_json=data.get("script_json", {}),
            script_fountain=data.get("script_fountain", ""),
            characters=data.get("characters", []),
            chapters=chapters,
            embeddings_map={int(k): v for k, v in data.get("embeddings_map", {}).items()},
            knowledge_graph=kg,
            token_usage=data.get("token_usage", {}),
            error_message=data.get("error_message", ""),
        )


# ---------------------------------------------------------------------------
# Redis storage helpers
# ---------------------------------------------------------------------------

REDIS_PIPELINE_INPUT_PREFIX = "pipeline:input:"
REDIS_PIPELINE_INPUT_TTL = 600  # 10 minutes — enough for Celery to pick up

REDIS_RESULT_PREFIX = "pipeline:result:"
REDIS_RESULT_TTL = 3600  # 1 hour — matches Celery result_expires


def store_pipeline_input(redis_client, task_id: str, data: PipelineInput) -> None:
    """Serialize *data* and store it in Redis under *task_id*."""
    import json
    serialized = json.dumps(data.to_dict(), ensure_ascii=False)
    redis_client.setex(
        f"{REDIS_PIPELINE_INPUT_PREFIX}{task_id}",
        REDIS_PIPELINE_INPUT_TTL,
        serialized,
    )
    logger.info("Stored pipeline input for task %s (%d bytes)", task_id, len(serialized))


def load_pipeline_input(redis_client, task_id: str) -> PipelineInput | None:
    """Load and deserialize pipeline input from Redis."""
    import json
    raw = redis_client.get(f"{REDIS_PIPELINE_INPUT_PREFIX}{task_id}")
    if not raw:
        logger.warning("Pipeline input not found in Redis for task %s", task_id)
        return None
    try:
        data = json.loads(raw)
        return PipelineInput.from_dict(data)
    except Exception as exc:
        logger.exception("Failed to deserialize pipeline input for %s: %s", task_id, exc)
        return None


def store_pipeline_result(redis_client, task_id: str, output: PipelineOutput) -> None:
    """Store pipeline result in Redis for the Main process to consume."""
    import json
    serialized = json.dumps(output.to_dict(), ensure_ascii=False)
    redis_client.setex(
        f"{REDIS_RESULT_PREFIX}{task_id}",
        REDIS_RESULT_TTL,
        serialized,
    )
    logger.info("Stored pipeline result for task %s (%d bytes)", task_id, len(serialized))


def load_pipeline_result(redis_client, task_id: str) -> PipelineOutput | None:
    """Load and deserialize pipeline result from Redis."""
    import json
    raw = redis_client.get(f"{REDIS_RESULT_PREFIX}{task_id}")
    if not raw:
        return None
    try:
        return PipelineOutput.from_dict(json.loads(raw))
    except Exception as exc:
        logger.exception("Failed to deserialize pipeline result for %s: %s", task_id, exc)
        return None
