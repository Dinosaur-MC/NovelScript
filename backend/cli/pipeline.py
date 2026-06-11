"""Pipeline engine — main orchestrator for novel-to-script conversion.

Usage:
    uv run python -m cli.pipeline <input_file> [-o output.yaml] [-n N] [-c C] [-s STYLE]
    uv run python -m cli.pipeline <directory/>  [-o output.yaml] [-n N] [-c C] [-s STYLE]

When *input* is a directory, all ``.txt`` / ``.md`` / ``.utf8`` files are
read in alphabetical order, each treated as a separate chapter.  This is
convenient for novels where each chapter is a single file.

``-n N`` / ``--limit N`` restricts processing to the first N chapters.
``-c C`` / ``--concurrency C`` caps concurrent LLM API calls (default 20,
also settable via ``LLM_MAX_CONCURRENCY`` env var).
``-s STYLE`` / ``--style STYLE`` injects AI scriptwriting direction into
the conversion & optimization prompts (e.g. "悬疑风格，注重氛围渲染").

Stages:
    1. Chunking      — split raw novel into chapters
    2. Summarize     — per-chapter objective summary (Flash, parallel)
    3. RAG Index     — build FAISS index for cross-chapter context
    4. GraphRAG      — extract knowledge graph (Pro, with RAG context)
    5. Conversion    — convert each chapter to script scenes (Flash, parallel)
    6. Optimization  — cross-scene consistency check (Pro, batched)
    7. Narrative Summary — one-paragraph overview from chapter summaries (Flash)
    8. Export        — YAML / JSON to stdout or file

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
from cli.element_fixer import fix_element_types, split_embedded_character, flag_missing_source_refs
from cli.exporter import to_yaml
from cli.fountain_exporter import to_fountain
from cli.graphrag_builder import extract_graph, extract_graph_incremental
from cli.heading_normalizer import normalize_heading
from cli.llm_router import get_llm, get_llm_semaphore, invoke_llm_with_retry, reset_token_usage, get_token_usage
from cli.models import Chapter, KnowledgeGraph, Scene, Script
from cli.optimizer import optimize
from cli.rag_builder import build_index, search
from cli.scene_merger import merge_tiny_scenes
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


async def run(
    input_path: str,
    *,
    limit: int | None = None,
    style_direction: str = "",
) -> Script:
    """Execute the full pipeline on a novel file or directory.

    Args:
        input_path: Path to a UTF-8 plain-text novel file, or a directory
                    containing ``.txt`` / ``.md`` files (one per chapter, read in
                    alphabetical order).
        limit:      Maximum number of chapters to process (``None`` = all).
                    Applied after sorting; the first *limit* files/chapters
                    are kept in alphabetical / occurrence order.
        style_direction:  Optional AI scriptwriting / style instruction
                    injected into the Conversion and Optimization prompts
                    (e.g. "悬疑风格", "更加黑暗").

    Returns:
        A complete Script model ready for export.

    When *input_path* is a directory each ``.txt`` / ``.md`` file is treated as a
    single pre-split chapter — the chunking stage is skipped entirely.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    if path.is_dir():
        txt_files = sorted(
            p for p in path.iterdir()
            if p.suffix.lower() in (".txt", ".utf8", ".utf-8", ".md")
        )
        if not txt_files:
            raise FileNotFoundError(f"No .txt / .md files found in directory: {input_path}")

        logger.info("Reading %d pre-split chapter(s) from directory: %s",
                     len(txt_files), path.name)
        chapters: list[Chapter] = []
        for i, f in enumerate(txt_files):
            text = f.read_text(encoding="utf-8").strip()
            if text:
                # Use filename stem as chapter title, strip leading numbers
                title = f.stem
                chapters.append(Chapter(text=text, title=title, index=i))

        if not chapters:
            raise ValueError(f"All chapter files in {input_path} are empty.")

        if limit is not None and limit > 0:
            chapters = chapters[:limit]

        logger.info("Loaded %d chapter(s) (chunking skipped).", len(chapters))
        return await run_from_chapters(
            chapters, source_name=path.name, style_direction=style_direction,
        )

    raw_text = path.read_text(encoding="utf-8")
    return await run_from_text(
        raw_text, source_name=path.name, limit=limit, style_direction=style_direction,
    )


async def run_from_text(
    raw_text: str,
    progress_callback: ProgressCallback | None = None,
    source_name: str = "",
    *,
    limit: int | None = None,
    style_direction: str = "",
) -> Script:
    """Execute the full pipeline on in-memory *raw_text*.

    Args:
        raw_text:     The complete novel as a single UTF-8 string.
        progress_callback:  Optional ``(percent, stage)`` reporter for SSE / UI.
        source_name:  Human-readable label for the ``meta.source_file`` field
                      (e.g. the original filename or novel title).
        limit:        Maximum number of chapters to process (``None`` = all).
        style_direction:  Optional AI scriptwriting / style instruction.

    Returns:
        A complete Script model ready for export.
    """
    chapters = split_chapters(raw_text)
    if limit is not None and limit > 0:
        chapters = chapters[:limit]
    return await run_from_chapters(
        chapters, progress_callback=progress_callback, source_name=source_name,
        style_direction=style_direction,
    )


async def run_from_chapters(
    chapters: list[Chapter],
    progress_callback: ProgressCallback | None = None,
    source_name: str = "",
    *,
    faiss_index=None,  # pre-built FAISS index — skips stage 3 when set
    kg: KnowledgeGraph | None = None,  # pre-built KG — skips stage 4 when set
    style_direction: str = "",
) -> Script:
    """Execute the full pipeline on pre-built *chapters*.

    Args:
        chapters:     Ordered list of already-split Chapter objects.
        progress_callback:  Optional ``(percent, stage)`` reporter for SSE / UI.
        source_name:  Human-readable label for the ``meta.source_file`` field.
        faiss_index:  Pre-built FAISS index for cross-chapter RAG context.
                      When ``None`` (default), the index is built from scratch.
        kg:           Pre-built KnowledgeGraph.  When ``None`` (default),
                      the KG is extracted via LLM (stage 4).
        style_direction:  Optional AI scriptwriting / style instruction
                      injected into Conversion and Optimization prompts.

    Returns:
        A complete Script model ready for export.

    When *chapters* are pre-built (e.g. from a directory of per-chapter
    files or from the database), the chunking stage is skipped entirely.
    When *faiss_index* or *kg* are provided, their corresponding stages
    are skipped — this enables cached reuse from the database across
    multiple pipeline runs.
    """
    started = time.monotonic()
    reset_token_usage()
    cb = progress_callback
    total_chars = sum(len(c.text) for c in chapters)
    logger.info("Loaded %d chapter(s) (%d chars).", len(chapters), total_chars)
    _call_cb(cb, 5, "chunking")  # chapters already split — skip to 5%

    # Pre-compute chapter texts list for RAG fallback (used by both
    # GraphRAG and Conversion stages)
    all_chapter_texts = [c.text for c in chapters]

    # ------------------------------------------------------------------
    # 2. Chapter Summarization (parallel)
    # ------------------------------------------------------------------
    logger.info("=== Stage 2: Chapter Summarization ===")
    summaries: list[str] = [""] * len(chapters)

    llm_sem = get_llm_semaphore()

    async def summarize_one(ch: Chapter) -> tuple[int, str]:
        # The summarizer only needs the chapter text (no KG dependency),
        # so it can run before GraphRAG.
        async with llm_sem:
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
    # 3. RAG — build FAISS index (or use cached)
    # ------------------------------------------------------------------
    if faiss_index is not None:
        logger.info("=== Stage 3: RAG Index (cached) ===")
        logger.info("FAISS index provided — embedding API call skipped.")
    else:
        logger.info("=== Stage 3: RAG Index Building ===")
        faiss_index = build_index(chapters)
    _call_cb(cb, 25, "rag")

    # ------------------------------------------------------------------
    # 4. GraphRAG — knowledge graph extraction (or use cached)
    # ------------------------------------------------------------------
    if kg is not None:
        logger.info("=== Stage 4: Knowledge Graph (cached) ===")
        logger.info("KG provided: %d node(s), %d edge(s) — LLM extraction skipped.",
                     len(kg.nodes), len(kg.edges))
    else:
        logger.info("=== Stage 4: Knowledge Graph Extraction ===")
        if len(chapters) > 5:
            # Incremental: chapter-by-chapter, prior entities as context.
            # Scales to 100+ chapters without exceeding context windows.
            kg = extract_graph_incremental(
                chapters,
                faiss_index=faiss_index,
                all_chapter_texts=all_chapter_texts,
            )
        else:
            # Single-shot: all chapters in one prompt.  Faster for short
            # novels (≤5 chapters) where context-fit isn't a concern.
            kg = extract_graph(
                chapters,
                faiss_index=faiss_index,
                all_chapter_texts=all_chapter_texts,
            )
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
        async with llm_sem:
            result = await asyncio.to_thread(
                convert_chapter, ch, kg, rag_ctx,
                chapter_summary=ch_summary,
                style_direction=style_direction,
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
    # 5.5. Post-processing (deterministic, no LLM calls)
    # ------------------------------------------------------------------
    logger.info("=== Stage 5.5: Post-Processing ===")

    # 5.5a. Assign globally unique scene IDs
    _assign_scene_ids(all_scenes)

    # 5.5b. Normalize scene headings (now returns structured Heading objects)
    for scene in all_scenes:
        scene.heading = normalize_heading(scene.heading)

    # 5.5c. Fix element type misclassifications + split embedded characters
    for scene in all_scenes:
        scene.elements = fix_element_types(scene.elements)
        scene.elements = split_embedded_character(scene.elements)

    # 5.5d. Merge tiny adjacent scenes (same location, compatible time)
    merged_scenes = merge_tiny_scenes(all_scenes)
    logger.info("Post-processing: %d → %d scenes.", len(all_scenes), len(merged_scenes))
    _call_cb(cb, 78, "post-processing")

    # ------------------------------------------------------------------
    # 6. Optimization — cross-scene consistency
    # ------------------------------------------------------------------
    logger.info("=== Stage 6: Scene Optimization ===")
    optimized_scenes = await optimize(merged_scenes, kg, style_direction=style_direction)
    logger.info("Optimized %d scene(s).", len(optimized_scenes))
    _call_cb(cb, 90, "optimizing")

    # ------------------------------------------------------------------
    # 7. Assemble Script
    # ------------------------------------------------------------------
    logger.info("=== Stage 7: Assembly ===")

    # Build narrative summary FIRST — it makes an LLM call that should be
    # included in the token usage report.
    narrative = _narrative_summary(summaries, kg)

    # Chapter order validation
    chapter_validation = _validate_chapter_order(chapters)

    # Narrative frame detection (after heading normalization)
    narrative_structure = _classify_narrative_layers(optimized_scenes)

    # Collect null-ref warnings from all scenes
    null_ref_warnings: list[dict] = []
    for scene in optimized_scenes:
        flagged = flag_missing_source_refs(scene.elements)
        if flagged:
            for f in flagged:
                f["scene_id"] = scene.scene_id
            null_ref_warnings.extend(flagged)

    # Capture token usage after ALL LLM calls have completed
    usage = get_token_usage()

    meta = {
        "source_file": source_name or "<text>",
        "source_chars": total_chars,
        "chapter_count": len(chapters),
        "scene_count": len(optimized_scenes),
        "pipeline_version": "0.3.0",
        "chapter_summaries": summaries,
        "chapter_validation": chapter_validation,
        "narrative_structure": narrative_structure,
        "null_source_ref_warnings": null_ref_warnings,
        "usage": usage,
        "usage_summary": (
            f"总调用 {sum(v.get('calls', 0) for k, v in usage.items() if k != 'total_cost_yuan')} 次, "
            f"总费用 ¥{usage.get('total_cost_yuan', 0):.4f}"
        ),
    }

    from cli.models import Character as ScriptCharacter

    characters = [
        ScriptCharacter(
            id=n.id,
            name=n.label,
            aliases=n.metadata.get("aliases", []),
            description="，".join(n.metadata.get("traits", [])) if n.metadata.get("traits") else "",
            metadata={k: v for k, v in n.metadata.items() if k not in ("aliases", "traits")},
        )
        for n in kg.nodes
        if n.type == "character"
    ]

    # Build title_page from source metadata
    from datetime import datetime, timezone

    from cli.models import SystemMeta, TitlePage

    title_page = TitlePage(
        title=source_name or "Untitled",
        draft_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    usage_summary_text = (
        f"总调用 {sum(v.get('calls', 0) for k, v in usage.items() if k != 'total_cost_yuan')} 次, "
        f"总费用 ¥{usage.get('total_cost_yuan', 0):.4f}"
    )

    system_meta = SystemMeta(
        document_id=source_name or "",
        model=_detect_model(usage),
        source_word_count=total_chars,
        warnings=[w["content_preview"] for w in null_ref_warnings[:10]],
    )

    # Preserve pipeline-internal diagnostics in system_meta.warnings
    if usage_summary_text:
        if len(system_meta.warnings) < 20:
            system_meta.warnings.append(usage_summary_text)

    script = Script(
        title_page=title_page,
        system_meta=system_meta,
        meta=meta,
        summary=narrative,
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


def _assign_scene_ids(scenes: list[Scene]) -> list[Scene]:
    """Assign globally unique, sequential scene IDs across all chapters.

    Scene IDs follow the pattern ``s_{global_index:04d}``, e.g. s_0001, s_0002.
    IDs are assigned in chapter order; within a chapter, scenes keep their
    relative order.
    """
    for i, scene in enumerate(scenes, 1):
        scene.scene_id = f"s_{i:04d}"
    return scenes


def _validate_chapter_order(chapters: list[Chapter]) -> dict:
    """Check if chapters are in chronological order.

    Detects:
    - Out-of-order chapter indices
    - Non-contiguous chapter sequences
    - Potential time-gaps between chapters

    Returns a warnings dict for inclusion in Script.meta.
    """
    warnings: list[str] = []
    indices = [ch.index for ch in chapters]

    # Check for non-monotonic indices
    for i in range(1, len(indices)):
        if indices[i] < indices[i - 1]:
            warnings.append(
                f"Chapter {chapters[i].title} (index {indices[i]}) appears after "
                f"chapter {chapters[i-1].title} (index {indices[i-1]}) — "
                f"possible timeline inversion"
            )

    # Check for gaps
    for i in range(1, len(indices)):
        gap = indices[i] - indices[i - 1]
        if gap > 1:
            warnings.append(
                f"Gap of {gap - 1} chapter(s) between chapter "
                f"{chapters[i-1].title} and {chapters[i].title}"
            )

    return {
        "chapter_count": len(chapters),
        "chapter_indices": [ch.index for ch in chapters],
        "is_monotonic": indices == sorted(indices),
        "warnings": warnings,
    }


def _classify_narrative_layers(scenes: list[Scene]) -> dict:
    """Detect and annotate narrative frame structure.

    Returns metadata for inclusion in the script output::

        {
            "has_frame_narrative": bool,
            "layers": {
                "FRAME": ["s_0001", "s_0002", ...],
                "FLASHBACK": ["s_0005", ...],
                "FLASHBACK_NESTED": [...],
            }
        }
    """
    layers: dict[str, list[str]] = {
        "FRAME": [],
        "FLASHBACK": [],
        "FLASHBACK_NESTED": [],
    }
    current_layer = "FRAME"

    for scene in scenes:
        heading_text = scene.heading.text if hasattr(scene.heading, "text") else str(scene.heading)
        if heading_text.startswith("FRAME:") or "FRAME:" in heading_text:
            current_layer = "FRAME"
            layers["FRAME"].append(scene.scene_id)
        elif "(FLASHBACK WITHIN FLASHBACK)" in heading_text:
            current_layer = "FLASHBACK_NESTED"
            layers["FLASHBACK_NESTED"].append(scene.scene_id)
        elif "(FLASHBACK)" in heading_text:
            current_layer = "FLASHBACK"
            layers["FLASHBACK"].append(scene.scene_id)
        else:
            layers[current_layer].append(scene.scene_id)

    has_frame = bool(layers["FLASHBACK"])  # FLASHBACK existence implies frame
    return {"has_frame_narrative": has_frame, "layers": layers}


def _narrative_summary(summaries: list[str], kg: KnowledgeGraph) -> str:
    """Generate a narrative one-paragraph overview from chapter summaries.

    Uses Flash for a low-cost natural-language summary covering the full story
    arc, key characters, and setting.  Falls back to a programmatic summary on
    LLM failure or when no chapter summaries are available.
    """
    valid = [s for s in summaries if s]
    if not valid:
        return _programmatic_summary(kg)

    combined = "\n\n---\n\n".join(
        f"第{i+1}章摘要：{s}" for i, s in enumerate(valid)
    )

    prompt = (
        "你是一个剧本策划。根据以下每章的事件摘要，用一段话概括整部小说的故事——"
        "包含主角、核心冲突、主要事件和整体基调。控制在 300 字以内，不要使用"
        "'这部小说'、'这个故事'等元描述。\n\n" + combined
    )

    try:
        llm = get_llm("chapter_summary", temperature=0.3, json_mode=False)
        resp = invoke_llm_with_retry(llm, prompt, "chapter_summary")
        return resp.content.strip()  # type: ignore[union-attr]
    except Exception:
        logger.exception("Narrative summary failed — falling back to programmatic summary.")
        return _programmatic_summary(kg)


def _detect_model(usage: dict) -> str:
    """Extract the primary model name from token-usage records."""
    for key in usage:
        if key not in ("total_cost_yuan",):
            return key
    return "unknown"


def _programmatic_summary(kg: KnowledgeGraph) -> str:
    """Fallback: count-based summary when LLM is unavailable."""
    char_names = [n.label for n in kg.nodes if n.type == "character"]
    loc_names = [n.label for n in kg.nodes if n.type == "location"]
    ec = len([n for n in kg.nodes if n.type == "event"])
    return (
        f"共 {len(char_names)} 个主要角色"
        + (f"（{', '.join(char_names[:8])}...）" if len(char_names) > 8 else f"（{', '.join(char_names)}）")
        + f"，{len(loc_names)} 个地点，{ec} 个关键事件。"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry: uv run python -m cli.pipeline <INPUT> [-o OUTPUT] [--json] [-n N] [-c C] [-s STYLE]

    When ``-o`` / ``--output`` is given the result is written to that
    file (logs go to stderr only).  Otherwise it is printed to stdout.
    ``--json`` exports JSON instead of the default YAML.
    ``-n N`` / ``--limit N`` restricts processing to the first N chapters.
    ``-c C`` / ``--concurrency C`` caps concurrent LLM calls (default: 20).
    ``-s STYLE`` / ``--style STYLE`` injects AI scriptwriting direction
    (e.g. "悬疑风格，注重氛围渲染").
    """
    import argparse
    import os

    # On Windows the default console codepage cannot encode CJK characters.
    # Reconfigure stdout/stderr for UTF-8 so the YAML output doesn't crash.
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="NovelScript Pipeline — convert a novel to a structured script.",
    )
    parser.add_argument(
        "input",
        help="Path to a UTF-8 plain-text novel file, or a directory of .txt / .md files "
             "(one per chapter, read in alphabetical order).",
    )
    parser.add_argument(
        "-o", "--output", metavar="OUTPUT", default=None,
        help="Write result to this file instead of stdout.",
    )
    parser.add_argument(
        "--json", dest="format_json", action="store_true",
        help="Export as JSON instead of YAML.",
    )
    parser.add_argument(
        "--fountain", dest="format_fountain", action="store_true",
        help="Export as Fountain (.fountain) screenplay format instead of YAML.",
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=None, metavar="N",
        help="Limit processing to the first N chapters (for quick testing).",
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=None, metavar="C",
        help="Maximum concurrent LLM API calls (default: 20).  "
             "Also settable via LLM_MAX_CONCURRENCY env var.",
    )
    parser.add_argument(
        "-s", "--style", type=str, default="", metavar="STYLE",
        help="AI scriptwriting direction injected into conversion & optimization "
             "prompts (e.g. '悬疑风格，注重氛围渲染').",
    )
    args = parser.parse_args()

    # Apply CLI override early — the semaphore reads this env var on first access.
    if args.concurrency is not None:
        os.environ["LLM_MAX_CONCURRENCY"] = str(args.concurrency)

    try:
        script = asyncio.run(run(args.input, limit=args.limit, style_direction=args.style))
        if args.format_fountain:
            output = to_fountain(script)
        elif args.format_json:
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
