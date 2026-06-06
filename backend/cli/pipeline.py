"""Pipeline engine — main orchestrator for novel-to-script conversion.

Usage:
    uv run python -m cli.pipeline <input_file>

Stages:
    1. Chunking     — split raw novel into chapters
    2. Summarize    — per-chapter objective summary (Flash, parallel)
    3. RAG Index    — build FAISS index for cross-chapter context
    4. GraphRAG     — extract knowledge graph (Pro, with RAG context)
    5. Conversion   — convert each chapter to script scenes (Flash, parallel)
    6. Optimization — cross-scene consistency check (Pro, batched)
    7. Export       — YAML to stdout

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
from cli.summarizer import summarize_chapter

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
    _call_cb(cb, 5, "chunking")

    # Pre-compute chapter texts list for RAG fallback (used by both
    # GraphRAG and Conversion stages)
    all_chapter_texts = [c.text for c in chapters]

    # ------------------------------------------------------------------
    # 2. Chapter Summarization (parallel)
    # ------------------------------------------------------------------
    logger.info("=== Stage 2: Chapter Summarization ===")
    summaries: list[str] = [""] * len(chapters)

    async def summarize_one(ch: Chapter) -> tuple[int, str]:
        # The summarizer only needs the chapter text (no KG dependency),
        # so it can run before GraphRAG.
        result = await asyncio.to_thread(summarize_chapter, ch)
        return ch.index, result

    if chapters:
        sum_tasks = [summarize_one(ch) for ch in chapters]
        sum_results = await asyncio.gather(*sum_tasks)
        for idx, s in sum_results:
            summaries[idx] = s
        logger.info("Summarized %d chapter(s).", len(chapters))
    _call_cb(cb, 15, "summarizing")

    # ------------------------------------------------------------------
    # 3. RAG — build FAISS index
    # ------------------------------------------------------------------
    logger.info("=== Stage 3: RAG Index Building ===")
    faiss_index = build_index(chapters)
    _call_cb(cb, 25, "rag")

    # ------------------------------------------------------------------
    # 4. GraphRAG — knowledge graph extraction (with RAG context)
    # ------------------------------------------------------------------
    logger.info("=== Stage 4: Knowledge Graph Extraction ===")
    kg = extract_graph(chapters, faiss_index=faiss_index,
                       all_chapter_texts=all_chapter_texts)
    logger.info(
        "KG: %d node(s), %d edge(s).",
        len(kg.nodes),
        len(kg.edges),
    )
    _call_cb(cb, 35, "graphrag")

    # ------------------------------------------------------------------
    # 5. Conversion — chapter → scenes (concurrent)
    # ------------------------------------------------------------------
    logger.info("=== Stage 5: Scene Conversion ===")

    all_scenes: list[Scene] = []
    chapter_count = len(chapters)
    completed_count = 0

    async def convert_one(ch: Chapter) -> list[Scene]:
        nonlocal completed_count
        rag_ctx = search(faiss_index, ch.text[:800], k=3,
                         fallback_texts=all_chapter_texts)
        ch_summary = summaries[ch.index] if ch.index < len(summaries) else ""
        result = await asyncio.to_thread(
            convert_chapter, ch, kg, rag_ctx,
            chapter_summary=ch_summary,
        )
        completed_count += 1
        progress = 35 + int((completed_count / max(chapter_count, 1)) * 40)
        _call_cb(cb, progress, "converting")
        return result

    tasks = [convert_one(ch) for ch in chapters]
    results = await asyncio.gather(*tasks)

    for i, scenes in enumerate(results):
        all_scenes.extend(scenes)
        logger.info("  Chapter %d → %d scene(s)", i, len(scenes))

    logger.info("Total scenes converted: %d", len(all_scenes))
    _call_cb(cb, 75, "converting")

    # ------------------------------------------------------------------
    # 6. Optimization — cross-scene consistency
    # ------------------------------------------------------------------
    logger.info("=== Stage 6: Scene Optimization ===")
    optimized_scenes = await asyncio.to_thread(optimize, all_scenes, kg)
    logger.info("Optimized %d scene(s).", len(optimized_scenes))
    _call_cb(cb, 90, "optimizing")

    # ------------------------------------------------------------------
    # 7. Assemble Script
    # ------------------------------------------------------------------
    logger.info("=== Stage 7: Assembly ===")

    # Store chapter summaries in meta for potential reuse
    meta = {
        "source_file": source_name or "<text>",
        "source_chars": total_chars,
        "chapter_count": len(chapters),
        "scene_count": len(optimized_scenes),
        "pipeline_version": "0.2.0",
        "chapter_summaries": summaries,
    }

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
    """CLI entry: uv run python -m cli.pipeline <INPUT> [-o OUTPUT] [--json]

    When ``-o`` / ``--output`` is given the result is written to that
    file (logs go to stderr only).  Otherwise it is printed to stdout.
    ``--json`` exports JSON instead of the default YAML.
    """
    import argparse

    # On Windows the default console codepage cannot encode CJK characters.
    # Reconfigure stdout/stderr for UTF-8 so the YAML output doesn't crash.
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="NovelScript Pipeline — convert a novel to a structured script.",
    )
    parser.add_argument("input", help="Path to a UTF-8 plain-text novel file.")
    parser.add_argument(
        "-o", "--output", metavar="OUTPUT", default=None,
        help="Write result to this file instead of stdout.",
    )
    parser.add_argument(
        "--json", dest="format_json", action="store_true",
        help="Export as JSON instead of YAML.",
    )
    args = parser.parse_args()

    try:
        script = asyncio.run(run(args.input))
        if args.format_json:
            from cli.exporter import to_json

            output = to_json(script)
        else:
            output = to_yaml(script)

        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            logger.info("Output written to %s (%d chars).", args.output, len(output))
        else:
            print(output)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        logger.exception("Pipeline failed with unhandled exception.")
        sys.exit(1)


if __name__ == "__main__":
    main()
