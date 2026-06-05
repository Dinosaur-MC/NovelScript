"""Scene optimizer — cross-scene consistency check.

Uses LangChain-native ChatPromptTemplate + with_structured_output().
"""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from cli.llm_router import get_llm
from cli.models import KnowledgeGraph, Scene

logger = logging.getLogger(__name__)


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list, description="优化后的场景列表")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个剧本质量控制专家。检查并修正剧本场景中的一致性问题：
1. 人物弧光一致性 2. 地点连续性 3. 时间线 4. 对白风格。
仅修正明显的不一致，保留原文风格和内容精髓。"""),
    ("human", """\
请检查以下剧本场景的一致性并进行修正：

{kg_summary}
【场景列表】
{scenes_json}"""),
])


def optimize(scenes: list[Scene], kg: KnowledgeGraph) -> list[Scene]:
    if not scenes:
        return []

    llm = get_llm("consistency_check", temperature=0.2)
    structured_llm = llm.with_structured_output(SceneList)

    try:
        result: SceneList = structured_llm.invoke(
            _PROMPT.invoke({
                "scenes_json": _serialize_scenes(scenes)[:12000],
                "kg_summary": _summarize_kg(kg),
            })
        )
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
