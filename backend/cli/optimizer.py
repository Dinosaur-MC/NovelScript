"""Scene optimizer — cross-scene consistency check.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).
"""

from __future__ import annotations

import json
import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from cli.llm_router import get_llm
from cli.models import KnowledgeGraph, Scene

logger = logging.getLogger(__name__)


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list, description="优化后的场景列表")


_parser = JsonOutputParser(pydantic_object=SceneList)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个剧本质量控制专家。检查并修正剧本场景中的一致性问题：
1. 人物弧光一致性 2. 地点连续性 3. 时间线 4. 对白风格。
仅修正明显的不一致，保留原文风格和内容精髓。

{format_instructions}"""),
    ("human", """\
请检查以下剧本场景的一致性并以 JSON 格式输出修正结果：

{kg_summary}
【场景列表】
{scenes_json}"""),
])


def optimize(scenes: list[Scene], kg: KnowledgeGraph) -> list[Scene]:
    if not scenes:
        return []

    llm = get_llm("consistency_check", temperature=0.2, json_mode=True)
    chain = _PROMPT | llm | _parser

    serialized = _serialize_scenes(scenes)
    if len(serialized) > 12000:
        logger.warning(
            "Scenes JSON is %d chars — truncating to 12000. "
            "%d of %d scenes may be dropped by the LLM.",
            len(serialized), max(0, len(scenes) - int(len(scenes) * 12000 / max(len(serialized), 1))), len(scenes),
        )

    try:
        raw = chain.invoke({
            "scenes_json": serialized[:12000],
            "kg_summary": _summarize_kg(kg),
            "format_instructions": _parser.get_format_instructions(),
        })
        result = SceneList.model_validate(raw) if isinstance(raw, dict) else raw
        # Restore source_ref tracing lost during serialization/LLM round-trip
        result.scenes = _restore_source_refs(scenes, result.scenes)
        logger.info("Optimizer: %d scene(s) processed.", len(result.scenes))
        return result.scenes
    except Exception as exc:
        logger.exception("Optimizer failed — returning original scenes: %s", exc)
        return scenes


def _serialize_scenes(scenes: list[Scene]) -> str:
    return json.dumps(
        [{"scene_id": s.scene_id, "heading": s.heading, "location": s.location,
          "time_of_day": s.time_of_day,
          "elements": [{"type": e.type, "content": e.content} for e in s.elements],
          "characters_present": s.characters_present} for s in scenes],
        ensure_ascii=False, indent=2,
    )


def _summarize_kg(kg: KnowledgeGraph) -> str:
    if not kg.nodes:
        return ""
    chars = [n for n in kg.nodes if n.node_type == "character"]
    return "人物参考：\n" + "\n".join(
        f"  {c.name} (traits: {c.properties.get('traits', [])})" for c in chars
    )


def _restore_source_refs(original: list[Scene], optimized: list[Scene]) -> list[Scene]:
    """Copy source_ref from *original* scenes onto *optimized* scenes.

    The LLM round-trip strips ``source_ref`` during serialization, so we
    rebuild it by matching elements on content within each scene pair.
    """
    # Build lookup: (scene_id, content) → source_ref
    ref_map: dict[tuple[str, str], dict] = {}
    for s in original:
        for e in s.elements:
            if e.source_ref:
                ref_map[(s.scene_id, e.content)] = e.source_ref

    for s in optimized:
        # Index-based fallback for elements whose content changed
        orig = _find_scene(original, s.scene_id)
        orig_elems = orig.elements if orig else []
        for i, e in enumerate(s.elements):
            if e.source_ref is not None:
                continue  # already has a ref
            key = (s.scene_id, e.content)
            if key in ref_map:
                e.source_ref = ref_map[key]
            elif i < len(orig_elems) and orig_elems[i].source_ref:
                # Position-based fallback when content was modified
                e.source_ref = orig_elems[i].source_ref

    return optimized


def _find_scene(scenes: list[Scene], scene_id: str) -> Scene | None:
    for s in scenes:
        if s.scene_id == scene_id:
            return s
    return None
