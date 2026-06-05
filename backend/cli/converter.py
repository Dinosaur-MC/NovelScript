"""Scene converter — transforms a novel chapter into script scenes.

Uses the Flash model with Knowledge Graph context and RAG context injected
into the prompt.  Every output element carries a ``source_ref`` anchor for
bidirectional traceability.  Pydantic validation with Auto-Fix (max 2 retries)
ensures schema compliance.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from cli.llm_router import get_llm
from cli.models import Chapter, Element, KnowledgeGraph, Scene

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
你是一个专业的影视剧本改编专家。你需要将小说章节转换为结构化的剧本场景。

每个场景 (scene) 包含以下字段：
- scene_id: 场景唯一标识符 (如 "s_001")
- heading: 场景标题 (slug line，如 "内. 京城大殿 - 日")
- location: 地点名称
- time_of_day: 时间 (日/夜/黄昏/清晨 等)
- elements: 剧本元素数组，每个元素包含:
    - type: 元素类型 (action/dialogue/heading/transition/parenthetical/character/note)
    - content: 元素文本内容
- characters_present: 该场景中出现的角色ID列表

剧本元素类型说明：
- heading: 场景标题/转场
- action: 动作描写/场景描述
- character: 角色名（对话前）
- dialogue: 角色对白
- parenthetical: 括号内的表演指示
- transition: 转场指示 (如 "切至:")
- note: 注释/说明

必须以严格的 JSON 数组格式输出：
```json
[
  {
    "scene_id": "s_001",
    "heading": "内. 京城大殿 - 日",
    "location": "京城大殿",
    "time_of_day": "日",
    "elements": [
      {"type": "action", "content": "大殿内，百官肃立。"},
      {"type": "dialogue", "content": "臣有本启奏。"}
    ],
    "characters_present": ["n_01"]
  }
]
```

规则：
- 对白必须使用 dialogue 类型，不要将角色名混入 content
- 保持原文风格，但去除小说化的描写（如心理活动）
- 将心理活动转换为 action (外部动作) 或 dialogue (对白)
- 每个场景集中在一个地点/时间
""")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_chapter(
    chapter: Chapter,
    kg: KnowledgeGraph,
    rag_context: list[str],
) -> list[Scene]:
    """Convert a single chapter into a list of script scenes.

    Args:
        chapter: The novel chapter to convert.
        kg: Knowledge graph for entity disambiguation.
        rag_context: Relevant text snippets from other chapters for context.

    Returns:
        List of validated Scene objects (empty list on failure).
    """
    llm = get_llm("scene_conversion", temperature=0.5)

    # Build context string
    kg_summary = _summarize_kg(kg)
    rag_text = "\n---\n".join(rag_context[:3]) if rag_context else "（无额外上下文）"

    for attempt in range(1 + MAX_RETRIES):
        try:
            raw_json = _call_llm(llm, chapter, kg_summary, rag_text, attempt)
            scenes = _parse_and_validate(raw_json, chapter.index)
            # Inject source_ref offsets
            scenes = _inject_source_refs(scenes, chapter)
            logger.info(
                "Chapter %d converted to %d scene(s).",
                chapter.index,
                len(scenes),
            )
            return scenes
        except Exception as exc:
            logger.warning(
                "Converter attempt %d/%d for chapter %d failed: %s",
                attempt + 1,
                1 + MAX_RETRIES,
                chapter.index,
                exc,
            )
            if attempt >= MAX_RETRIES:
                logger.exception(
                    "Converter: all retries exhausted for chapter %d.",
                    chapter.index,
                )
                return []

    return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _summarize_kg(kg: KnowledgeGraph) -> str:
    """Produce a compact text summary of the knowledge graph."""
    if not kg.nodes:
        return "（知识图谱为空）"

    lines = ["【知识图谱】"]
    char_nodes = [n for n in kg.nodes if n.node_type == "character"]
    loc_nodes = [n for n in kg.nodes if n.node_type == "location"]

    if char_nodes:
        lines.append("人物：")
        for n in char_nodes:
            aliases = n.properties.get("aliases", [])
            alias_str = f" (别名: {', '.join(aliases)})" if aliases else ""
            lines.append(f"  - {n.id}: {n.name}{alias_str}")

    if loc_nodes:
        lines.append("地点：")
        for n in loc_nodes:
            lines.append(f"  - {n.id}: {n.name}")

    if kg.edges:
        lines.append("关系：")
        for e in kg.edges:
            lines.append(f"  - {e.source_node_id} --[{e.relation}]--> {e.target_node_id}")

    return "\n".join(lines)


def _call_llm(
    llm,
    chapter: Chapter,
    kg_summary: str,
    rag_text: str,
    attempt: int,
) -> str:
    """Invoke the Flash model and return raw JSON text."""
    user_prompt = (
        f"请将以下小说章节转换为剧本场景。\n\n"
        f"章节: {chapter.title}\n\n"
        f"{kg_summary}\n\n"
        f"【相关上下文（其他章节片段）】\n{rag_text}\n\n"
        f"【待转换章节正文】\n{chapter.text[:8000]}"
    )

    if attempt > 0:
        user_prompt = (
            f"上一次转换结果不符合 JSON Schema 格式要求。"
            f"请严格按照指定的 JSON 格式重新转换。\n\n" + user_prompt
        )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    resp = llm.invoke(messages)
    raw: str = resp.content.strip()  # type: ignore[union-attr]

    # Strip markdown fences
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    return raw


def _parse_and_validate(raw_json: str, chapter_index: int) -> list[Scene]:
    """Parse JSON and validate as list[Scene]. Raises on failure."""
    data = json.loads(raw_json)
    if not isinstance(data, list):
        data = [data]

    scenes: list[Scene] = []
    for i, s in enumerate(data):
        elements = [
            Element(
                type=el["type"],
                content=el["content"],
            )
            for el in s.get("elements", [])
        ]
        scene = Scene(
            scene_id=s.get("scene_id", f"s_{chapter_index:03d}_{i:03d}"),
            heading=s.get("heading", ""),
            location=s.get("location", ""),
            time_of_day=s.get("time_of_day", ""),
            elements=elements,
            characters_present=s.get("characters_present", []),
        )
        scenes.append(scene)

    return scenes


def _inject_source_refs(scenes: list[Scene], chapter: Chapter) -> list[Scene]:
    """Add source_ref to each Element based on approximate text offsets.

    Uses coarse substring matching to find the element's content in the
    chapter text and record its span.
    """
    for scene in scenes:
        for elem in scene.elements:
            if elem.source_ref is not None:
                continue
            pos = chapter.text.find(elem.content)
            if pos != -1:
                elem.source_ref = {
                    "chapter_id": f"ch_{chapter.index:02d}",
                    "offset": [pos, pos + len(elem.content)],
                }
            else:
                elem.source_ref = {
                    "chapter_id": f"ch_{chapter.index:02d}",
                    "offset": None,
                }
    return scenes
