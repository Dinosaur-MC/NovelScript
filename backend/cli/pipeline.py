"""Pipeline engine — main orchestrator for novel-to-script conversion.

Usage:
    uv run python -m cli.pipeline <input_file>

Stages:
    1. Chunking    — split raw novel into chapters
    2. RAG Index   — build FAISS index for cross-chapter context
    3. GraphRAG    — extract knowledge graph (characters, locations, relations)
    4. Conversion  — convert each chapter to script scenes (Flash)
    5. Optimization — cross-scene consistency check (Pro)
    6. Export       — YAML to stdout

The ``run_from_text()`` entry point accepts an optional ``progress_callback``
so the backend's pipeline-executor thread can stream real-time SSE events.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env so os.getenv() works for DEEPSEEK_API_KEY etc.

from cli.chunker import split_chapters
from cli.converter import convert_chapter
from cli.exporter import to_yaml
from cli.graphrag_builder import extract_graph
from cli.models import Chapter, KnowledgeGraph, Scene, Script
from cli.optimizer import optimize
from cli.rag_builder import build_index, search

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s - %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    encoding="utf-8",
)
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, str], None]
"""A progress reporter: ``callback(percent: int, stage: str)``."""


def _call_cb(cb: ProgressCallback | None, progress: int, stage: str) -> None:
    """Invoke *cb* if not None, swallowing any exception it raises."""
    if cb is None:
        return
    try:
        cb(progress, stage)
    except Exception:
        logger.debug("Progress callback raised (ignored).", exc_info=True)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


async def run(file_path: str) -> Script:
    """Execute the full pipeline on the novel at *file_path*.

    Args:
        file_path: Path to a UTF-8 encoded plain-text novel file.

    Returns:
        A complete Script model ready for export.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    raw_text = path.read_text(encoding="utf-8")
    return await run_from_text(raw_text, source_name=path.name)


async def run_from_text(
    raw_text: str,
    progress_callback: ProgressCallback | None = None,
    source_name: str = "",
) -> Script:
    """Execute the full pipeline on in-memory *raw_text*.

    Args:
        raw_text:     The complete novel as a single UTF-8 string.
        progress_callback:  Optional ``(percent, stage)`` reporter for SSE / UI.
        source_name:  Human-readable label for the ``meta.source_file`` field
                      (e.g. the original filename or novel title).

    Returns:
        A complete Script model ready for export.
    """
    started = time.monotonic()
    cb = progress_callback
    total_chars = len(raw_text)
    logger.info("Loaded %s (%d chars).", source_name or "<text>", total_chars)
    _call_cb(cb, 0, "starting")

    # ------------------------------------------------------------------
    # 1. Chunking
    # ------------------------------------------------------------------
    logger.info("=== Stage 1: Chapter Chunking ===")
    chapters = split_chapters(raw_text)
    logger.info("Split into %d chapter(s).", len(chapters))
    _call_cb(cb, 10, "chunking")

    # ------------------------------------------------------------------
    # 2. RAG — build FAISS index
    # ------------------------------------------------------------------
    logger.info("=== Stage 2: RAG Index Building ===")
    faiss_index = build_index(chapters)
    _call_cb(cb, 25, "rag")

    # Pre-compute chapter texts list for RAG fallback (used by both
    # GraphRAG and Conversion stages)
    all_chapter_texts = [c.text for c in chapters]

    # ------------------------------------------------------------------
    # 3. GraphRAG — knowledge graph extraction (with RAG context)
    # ------------------------------------------------------------------
    logger.info("=== Stage 3: Knowledge Graph Extraction ===")
    kg = extract_graph(chapters, faiss_index=faiss_index,
                       all_chapter_texts=all_chapter_texts)
    logger.info(
        "KG: %d node(s), %d edge(s).",
        len(kg.nodes),
        len(kg.edges),
    )
    _call_cb(cb, 35, "graphrag")

    # ------------------------------------------------------------------
    # 4. Conversion — chapter → scenes (concurrent)
    # ------------------------------------------------------------------
    logger.info("=== Stage 4: Scene Conversion ===")

    all_scenes: list[Scene] = []
    chapter_count = len(chapters)
    completed_count = 0

    async def convert_one(ch: Chapter) -> list[Scene]:
        nonlocal completed_count
        rag_ctx = search(faiss_index, ch.text[:500], k=3,
                         fallback_texts=all_chapter_texts)
        result = await asyncio.to_thread(convert_chapter, ch, kg, rag_ctx)
        completed_count += 1
        progress = 35 + int((completed_count / max(chapter_count, 1)) * 45)
        _call_cb(cb, progress, "converting")
        return result

    tasks = [convert_one(ch) for ch in chapters]
    results = await asyncio.gather(*tasks)

    for i, scenes in enumerate(results):
        all_scenes.extend(scenes)
        logger.info("  Chapter %d → %d scene(s)", i, len(scenes))

    logger.info("Total scenes converted: %d", len(all_scenes))
    _call_cb(cb, 80, "converting")

    # ------------------------------------------------------------------
    # 5. Optimization — cross-scene consistency
    # ------------------------------------------------------------------
    logger.info("=== Stage 5: Scene Optimization ===")
    optimized_scenes = await asyncio.to_thread(optimize, all_scenes, kg)
    logger.info("Optimized %d scene(s).", len(optimized_scenes))
    _call_cb(cb, 95, "optimizing")

    # ------------------------------------------------------------------
    # 6. Assemble Script
    # ------------------------------------------------------------------
    logger.info("=== Stage 6: Assembly ===")

    from cli.models import Character as ScriptCharacter

    characters = [
        ScriptCharacter(
            id=n.id,
            name=n.name,
            aliases=n.properties.get("aliases", []),
            properties=n.properties,
        )
        for n in kg.nodes
        if n.node_type == "character"
    ]

    meta = {
        "source_file": source_name or "<text>",
        "source_chars": total_chars,
        "chapter_count": len(chapters),
        "scene_count": len(optimized_scenes),
        "pipeline_version": "0.1.0",
    }

    script = Script(
        meta=meta,
        summary=_generate_summary(optimized_scenes, kg),
        characters=characters,
        scenes=optimized_scenes,
        knowledge_graph=kg,
    )

    elapsed = time.monotonic() - started
    logger.info("Pipeline complete in %.1fs.", elapsed)
    _call_cb(cb, 100, "assembling")

    return script


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_summary(scenes: list[Scene], kg: KnowledgeGraph) -> str:
    """Generate a simple summary from scene count and character info."""
    char_names = [n.name for n in kg.nodes if n.node_type == "character"]
    loc_names = [n.name for n in kg.nodes if n.node_type == "location"]
    return (
        f"共 {len(scenes)} 个场景，"
        f"涉及 {len(char_names)} 个角色"
        + (f"（{', '.join(char_names[:5])}...）" if len(char_names) > 5 else f"（{', '.join(char_names)}）")
        + (f"，{len(loc_names)} 个地点。" if loc_names else "。")
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry: uv run python -m cli.pipeline <input_file>"""
    # On Windows the default console codepage cannot encode CJK characters.
    # Reconfigure stdout for UTF-8 so the YAML output doesn't crash.
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: uv run python -m cli.pipeline <input_file>", file=sys.stderr)
        sys.exit(2)

    input_file = sys.argv[1]

    try:
        script = asyncio.run(run(input_file))
        yaml_output = to_yaml(script)
        print(yaml_output)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        logger.exception("Pipeline failed with unhandled exception.")
        sys.exit(1)


if __name__ == "__main__":
    main()
