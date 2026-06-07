"""Scene converter — transforms a novel chapter into script scenes.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).
"""

from __future__ import annotations

import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from cli.llm_router import context_chars, get_llm, invoke_with_retry
from cli.models import Chapter, KnowledgeGraph, Scene
from cli.paragraph_splitter import split_paragraphs

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

=== 场景标题 (heading) 格式规则 ===
每个场景必须包含标准 slug line，格式严格遵循：
  INT./EXT. LOCATION - TIME_OF_DAY

规则：
- 前缀用 INT. 或 EXT.，不能用中文"内景/外景"
- 时间用英文：DAY, NIGHT, DUSK, DAWN, AFTERNOON, MORNING
- 如果是回忆场景，在末尾添加 (FLASHBACK)：EXT. 徐家田地 - DUSK (FLASHBACK)
- 如果是梦境，添加 (DREAM)：INT. 角色脑海 - NIGHT (DREAM)
- 不要使用"闪回"、"回忆"等中文标记
- 不要在一个 heading 中使用两个地点（用 / 分隔）
- 时间跳跃用 LATER 或 CONTINUOUS：EXT. 后山山顶 - DAY (LATER)

=== 叙事层级规则 ===
如果你检测到以下模式，请在 heading 中明确标记：
1. 第一人称叙述者框架 → heading 以 "FRAME:" 开头
   例：FRAME: EXT. 乡间田野 - AFTERNOON
2. 角色回忆/讲述的往事 → heading 末尾添加 (FLASHBACK)
   例：EXT. 徐家田地 - DUSK (FLASHBACK)
3. 回忆中的回忆（嵌套闪回）→ 使用 (FLASHBACK WITHIN FLASHBACK)
4. 回到框架叙述 → heading 以 "FRAME:" 开头

=== 对白保留规则（严格遵守）===
1. 原文中的对话，必须逐字保留，不得改写或简化
2. 不要添加原文没有的对话
3. 不要将原文的对话"现代化"或"合理化"
4. 如果原文的对话不完整或有歧义，保持原样，不要补充
5. 仅在原文的叙述性描写需要转换为对白时，才可创建新的 dialogue 元素
6. 创建的新对白必须在 source_ref 中标记 confidence: "inferred"

=== 一般规则 ===
对白使用 dialogue 类型，去除小说化描写，心理活动转换为 action 或 dialogue。
{style_instruction}

{format_instructions}"""),
    ("human", """\
请将以下小说章节转换为 JSON 格式的剧本场景。

章节: {chapter_title}
{summary_section}
{kg_summary}
【相关上下文】{rag_context}
【待转换章节正文】
{chapter_text}"""),
])


def convert_chapter(
    chapter: Chapter,
    kg: KnowledgeGraph,
    rag_context: list[str],
    chapter_summary: str = "",
    style_direction: str = "",
) -> list[Scene]:
    llm = get_llm("scene_conversion", temperature=0.5, json_mode=True)

    kg_summary = _summarize_kg(kg)
    # Truncate RAG passages to avoid flooding the prompt — each is capped
    # at 2000 chars (was unbounded; FAISS returns full chapter texts).
    rag_text = "\n---\n".join(
        r[:2000] for r in rag_context[:3]
    ) if rag_context else "（无额外上下文）"

    # Build chapter text from paragraph groups (boundary-aware, no raw truncation)
    budget = context_chars("converting")
    para_groups = split_paragraphs(chapter.text, max_chars=budget)
    chapter_text = para_groups[0].text if para_groups else chapter.text[:budget]

    # Inject chapter summary as "前情提要"
    summary_section = ""
    if chapter_summary:
        summary_section = (
            f"【前情提要】\n以下是本章之前发生过的事情摘要，供你理解上下文：\n{chapter_summary}\n"
        )

    # Build style instruction — nil when empty, guidance when set
    style_instruction = ""
    if style_direction:
        style_instruction = (
            f"【编剧指示】\n请按照以下风格/编剧指示调整剧本：{style_direction}\n"
        )

    chain = _PROMPT | llm | _parser
    prompt_inputs = {
        "chapter_title": chapter.title,
        "chapter_text": chapter_text,
        "kg_summary": kg_summary,
        "rag_context": rag_text,
        "summary_section": summary_section,
        "style_instruction": style_instruction,
        "format_instructions": _parser.get_format_instructions(),
    }

    try:
        raw = invoke_with_retry(chain, prompt_inputs, "scene_conversion")
        result = SceneList.model_validate(raw) if isinstance(raw, dict) else raw
        scenes = _inject_source_refs(result.scenes, chapter)
        logger.info("Chapter %d converted to %d scene(s).", chapter.index, len(scenes))
        return scenes
    except Exception as exc:
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
