"""Pipeline engine — main orchestrator for novel-to-script conversion.

Usage:
    uv run python -m cli.pipeline <input_file>

Stages:
    1. Chunking    — split raw novel into chapters
    2. GraphRAG    — extract knowledge graph (characters, locations, relations)
    3. RAG Index   — build FAISS index for cross-chapter context
    4. Conversion  — convert each chapter to script scenes (Flash)
    5. Optimization — cross-scene consistency check (Pro)
    6. Export       — YAML to stdout
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
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
)
logger = logging.getLogger("pipeline")


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
    started = time.monotonic()

    # ------------------------------------------------------------------
    # 0. Load raw text
    # ------------------------------------------------------------------
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    raw_text = path.read_text(encoding="utf-8")
    total_chars = len(raw_text)
    logger.info("Loaded %s (%d chars).", path.name, total_chars)

    # ------------------------------------------------------------------
    # 1. Chunking
    # ------------------------------------------------------------------
    logger.info("=== Stage 1: Chapter Chunking ===")
    chapters = split_chapters(raw_text)
    logger.info("Split into %d chapter(s).", len(chapters))

    # ------------------------------------------------------------------
    # 2. GraphRAG — knowledge graph extraction
    # ------------------------------------------------------------------
    logger.info("=== Stage 2: Knowledge Graph Extraction ===")
    kg = extract_graph(chapters)
    logger.info(
        "KG: %d node(s), %d edge(s).",
        len(kg.nodes),
        len(kg.edges),
    )

    # ------------------------------------------------------------------
    # 3. RAG — build FAISS index
    # ------------------------------------------------------------------
    logger.info("=== Stage 3: RAG Index Building ===")
    faiss_index = build_index(chapters)

    # ------------------------------------------------------------------
    # 4. Conversion — chapter → scenes (concurrent)
    # ------------------------------------------------------------------
    logger.info("=== Stage 4: Scene Conversion ===")

    all_scenes: list[Scene] = []

    async def convert_one(ch: Chapter) -> list[Scene]:
        rag_ctx = search(faiss_index, ch.text[:500], k=3)
        # Run the synchronous converter in a thread to avoid blocking
        return await asyncio.to_thread(convert_chapter, ch, kg, rag_ctx)

    tasks = [convert_one(ch) for ch in chapters]
    results = await asyncio.gather(*tasks)

    for i, scenes in enumerate(results):
        all_scenes.extend(scenes)
        logger.info("  Chapter %d → %d scene(s)", i, len(scenes))

    logger.info("Total scenes converted: %d", len(all_scenes))

    # ------------------------------------------------------------------
    # 5. Optimization — cross-scene consistency
    # ------------------------------------------------------------------
    logger.info("=== Stage 5: Scene Optimization ===")
    optimized_scenes = await asyncio.to_thread(optimize, all_scenes, kg)
    logger.info("Optimized %d scene(s).", len(optimized_scenes))

    # ------------------------------------------------------------------
    # 6. Assemble Script
    # ------------------------------------------------------------------
    logger.info("=== Stage 6: Assembly ===")

    # Derive characters from KG character nodes
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
        "source_file": path.name,
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
