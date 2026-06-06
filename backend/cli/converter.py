"""Scene converter — transforms a novel chapter into script scenes.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).
"""

from __future__ import annotations

import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from cli.llm_router import get_llm
from cli.models import Chapter, KnowledgeGraph, Scene

logger = logging.getLogger(__name__)


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list, description="剧本场景列表")


_parser = JsonOutputParser(pydantic_object=SceneList)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个专业的影视剧本改编专家。将小说章节转换为结构化的剧本场景。

每个场景 (scene) 包含: scene_id, heading (slug line), location, time_of_day,
elements (元素: action/dialogue/heading/transition/parenthetical/character/note,
每元素含 type + content), characters_present (角色ID列表)。

规则: 对白使用 dialogue 类型，去除小说化描写，心理活动转换为 action 或 dialogue。

{format_instructions}"""),
    ("human", """\
请将以下小说章节转换为 JSON 格式的剧本场景。

章节: {chapter_title}
{kg_summary}
【相关上下文】{rag_context}
【待转换章节正文】
{chapter_text}"""),
])


def convert_chapter(
    chapter: Chapter,
    kg: KnowledgeGraph,
    rag_context: list[str],
    max_retries: int = 1,
) -> list[Scene]:
    llm = get_llm("scene_conversion", temperature=0.5, json_mode=True)

    kg_summary = _summarize_kg(kg)
    # Truncate RAG passages to avoid flooding the prompt — each is capped
    # at 2000 chars (was unbounded; FAISS returns full chapter texts).
    rag_text = "\n---\n".join(
        r[:2000] for r in rag_context[:3]
    ) if rag_context else "（无额外上下文）"

    chain = _PROMPT | llm | _parser

    for attempt in range(max_retries + 1):
        try:
            raw = chain.invoke({
                "chapter_title": chapter.title,
                "chapter_text": chapter.text[:15000],
                "kg_summary": kg_summary,
                "rag_context": rag_text,
                "format_instructions": _parser.get_format_instructions(),
            })
            result = SceneList.model_validate(raw) if isinstance(raw, dict) else raw
            scenes = _inject_source_refs(result.scenes, chapter)
            logger.info("Chapter %d converted to %d scene(s).", chapter.index, len(scenes))
            return scenes
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(
                    "Converter retry %d/%d for chapter %d: %s",
                    attempt + 1, max_retries, chapter.index, exc,
                )
            else:
                logger.exception("Converter failed for chapter %d: %s", chapter.index, exc)
    return []


def _summarize_kg(kg: KnowledgeGraph) -> str:
    if not kg.nodes:
        return "（知识图谱为空）"
    lines = ["【知识图谱】"]
    for n in [n for n in kg.nodes if n.node_type == "character"]:
        aliases = n.properties.get("aliases", [])
        alias_str = f" (别名: {', '.join(aliases)})" if aliases else ""
        lines.append(f"  {n.id}: {n.name}{alias_str}")
    for n in [n for n in kg.nodes if n.node_type == "location"]:
        lines.append(f"  {n.id}: {n.name}")
    for e in kg.edges:
        lines.append(f"  {e.source_node_id} --[{e.relation}]--> {e.target_node_id}")
    return "\n".join(lines)


def _inject_source_refs(scenes: list[Scene], chapter: Chapter) -> list[Scene]:
    chapter_len = len(chapter.text)
    total_elements = sum(len(s.elements) for s in scenes)
    elem_seq = 0
    for scene in scenes:
        for elem in scene.elements:
            if elem.source_ref is not None:
                elem_seq += 1
                continue
            pos = chapter.text.find(elem.content)
            if pos == -1:
                prefix = elem.content[:10] if len(elem.content) >= 10 else elem.content
                pos = chapter.text.find(prefix)
            if pos != -1:
                offset_start, offset_end = pos, pos + len(elem.content)
            else:
                ratio = elem_seq / max(total_elements, 1)
                offset_start, offset_end = int(chapter_len * ratio), int(chapter_len * ratio) + len(elem.content)
            elem.source_ref = {
                "chapter_id": f"ch_{chapter.index:02d}",
                "offset": [offset_start, offset_end],
                "confidence": "exact" if pos != -1 else "estimated",
            }
            elem_seq += 1
    return scenes
