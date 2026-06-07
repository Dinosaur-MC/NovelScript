"""Scene optimizer — cross-scene consistency check.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).

When the serialized scene list exceeds the per-call budget, scenes are
split into batches.  Batches are **independent** — they are dispatched
concurrently via ``asyncio.gather`` so wall-clock time is bounded by the
slowest single batch rather than the sum of all batches.
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from cli.llm_router import get_llm, get_llm_semaphore, invoke_with_retry
from cli.models import KnowledgeGraph, Scene

logger = logging.getLogger(__name__)

# Per-batch serialized size budget (chars).  DeepSeek's context window
# is large enough that we can go higher, but staying conservative keeps
# the LLM focused on each batch's internal consistency.
_BATCH_BUDGET = 10_000


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list, description="优化后的场景列表")


_parser = JsonOutputParser(pydantic_object=SceneList)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个剧本质量控制专家。检查并修正剧本场景中的一致性问题：
1. 人物弧光一致性 2. 地点连续性 3. 时间线 4. 对白风格。

=== 对白保护规则 ===
- 保留对白的潜台词和语气，不要"合理化"或"现代化"对白
- 不要添加原文中没有的对话内容
- 不要改写角色对白使其"更符合逻辑"——角色的原话就是角色的声音
- 如果原文是口语化、粗俗或不完整的表达，保持原样

仅修正明显的不一致，保留原文风格和内容精髓。
{style_instruction}

{format_instructions}"""),
    ("human", """\
请检查以下剧本场景的一致性并以 JSON 格式输出修正结果：

{kg_summary}
{context_note}
【场景列表】
{scenes_json}"""),
])


async def optimize(
    scenes: list[Scene],
    kg: KnowledgeGraph,
    style_direction: str = "",
) -> list[Scene]:
    """Check and improve cross-scene consistency.

    Scenes are processed in batches so the per-call JSON payload stays
    within ``_BATCH_BUDGET`` characters — no scenes are silently dropped.

    Batches are independent and dispatched **concurrently** via
    ``asyncio.to_thread`` so wall-clock time is roughly the duration of
    the slowest batch, not the sum of all batches.
    """
    if not scenes:
        return []

    kg_summary = _summarize_kg(kg)
    format_instructions = _parser.get_format_instructions()
    batches = _batch_scenes(scenes)

    style_instruction = ""
    if style_direction:
        style_instruction = (
            f"【编剧指示】\n请按照以下风格/编剧指示调整剧本：{style_direction}\n"
        )

    if len(batches) == 1:
        logger.info("Optimizer: 1 batch (%d scenes).", len(scenes))
    else:
        logger.info(
            "Optimizer: %d scenes split into %d batches (concurrent).",
            len(scenes), len(batches),
        )

    llm_sem = get_llm_semaphore()

    async def _process_batch(bi: int, batch: list[Scene]) -> list[Scene]:
        """Run a single batch in a background thread (blocking LLM call)."""
        batch_json = _serialize_scenes(batch)
        context_note = ""
        if len(batches) > 1:
            context_note = (
                f"（这是第 {bi + 1}/{len(batches)} 批场景。"
                f"共 {len(scenes)} 个场景，本批 {len(batch)} 个。）"
            )

        try:
            async with llm_sem:
                raw = await asyncio.to_thread(
                    _invoke_chain, batch_json, kg_summary, format_instructions,
                    context_note, style_instruction,
                )
            result = SceneList.model_validate(raw) if isinstance(raw, dict) else raw
            logger.info(
                "  Batch %d/%d: %d → %d scenes.",
                bi + 1, len(batches), len(batch), len(result.scenes),
            )
            return result.scenes
        except Exception:
            logger.exception(
                "Batch %d/%d failed — keeping original scenes for this batch.",
                bi + 1, len(batches),
            )
            return batch

    # Dispatch all batches concurrently — each batch is an independent LLM call
    batch_results = await asyncio.gather(
        *[_process_batch(i, b) for i, b in enumerate(batches)],
    )

    # Flatten (batch_results preserves insertion order since gather does)
    optimized: list[Scene] = []
    for result in batch_results:
        optimized.extend(result)

    # Restore source_ref tracing lost during serialization/LLM round-trips
    optimized = _restore_source_refs(scenes, optimized)

    if len(optimized) != len(scenes):
        logger.warning(
            "Scene count changed during optimization: %d → %d.",
            len(scenes), len(optimized),
        )

    return optimized


def _invoke_chain(
    scenes_json: str,
    kg_summary: str,
    format_instructions: str,
    context_note: str,
    style_instruction: str = "",
) -> dict:
    """Shared LLM invocation — extracted so the batcher and tests can reuse it.
    Uses ``invoke_with_retry`` for transient-failure resilience.
    """
    llm = get_llm("consistency_check", temperature=0.2, json_mode=True)
    chain = _PROMPT | llm | _parser
    return invoke_with_retry(chain, {
        "scenes_json": scenes_json,
        "kg_summary": kg_summary,
        "style_instruction": style_instruction,
        "format_instructions": format_instructions,
        "context_note": context_note,
    }, "consistency_check")


def _serialize_scenes(scenes: list[Scene]) -> str:
    return json.dumps(
        [{"scene_id": s.scene_id, "heading": s.heading, "location": s.location,
          "time_of_day": s.time_of_day,
          "elements": [{"type": e.type, "content": e.content} for e in s.elements],
          "characters_present": s.characters_present} for s in scenes],
        ensure_ascii=False, indent=2,
    )


def _batch_scenes(scenes: list[Scene]) -> list[list[Scene]]:
    """Split *scenes* so each batch's serialization fits ``_BATCH_BUDGET``.

    Single-scene batches are emitted as-is even when they exceed the
    budget (one huge scene is better than dropping it).
    """
    batches: list[list[Scene]] = []
    current: list[Scene] = []
    current_size = 0

    for s in scenes:
        s_size = len(_serialize_scenes([s]))
        if current and current_size + s_size > _BATCH_BUDGET:
            batches.append(current)
            current = []
            current_size = 0
        current.append(s)
        current_size += s_size

    if current:
        batches.append(current)

    return batches


def _summarize_kg(kg: KnowledgeGraph) -> str:
    if not kg.nodes:
        return ""
    chars = [n for n in kg.nodes if n.node_type == "character"]
    return "人物参考：\n" + "\n".join(
        f"  {c.name} (traits: {c.properties.get('traits', [])})" for c in chars
    )


def _restore_source_refs(original: list[Scene], optimized: list[Scene]) -> list[Scene]:
    """Copy source_ref from *original* scenes onto *optimized* scenes.

    The LLM round-trip strips ``source_ref`` and may alter ``scene_id``
    values (e.g. ``s_007`` → ``s_007a``).  We therefore match **by
    position**: ``original[i]`` ↔ ``optimized[i]``.
    """
    for idx, (orig, opt) in enumerate(zip(original, optimized)):
        # Build a content→source_ref map for this original scene
        ref_map: dict[str, dict] = {}
        for e in orig.elements:
            if e.source_ref:
                ref_map[e.content] = e.source_ref

        for ei, elem in enumerate(opt.elements):
            if elem.source_ref is not None:
                continue  # already has a ref
            if elem.content in ref_map:
                elem.source_ref = ref_map[elem.content]
            elif ei < len(orig.elements) and orig.elements[ei].source_ref:
                # Position-based fallback when the LLM lightly edited content
                elem.source_ref = orig.elements[ei].source_ref

    return optimized


