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
from cli.models import (
    ActionElement,
    Chapter,
    DialogueBlock,
    KnowledgeGraph,
    Scene,
    ScriptElement,
    SourceRef,
)
from cli.paragraph_splitter import split_paragraphs

logger = logging.getLogger(__name__)


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list, description="剧本场景列表")


_parser = JsonOutputParser(pydantic_object=SceneList)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个专业的影视剧本改编专家。将小说章节转换为结构化的剧本场景。

每个场景 (scene) 包含: scene_id, heading (slug line 字符串),
characters_present (角色ID列表),
elements (元素列表，按时间顺序)。

=== 元素类型与字段 ===
必须使用以下元素类型，每种元素的字段不同：

1. action — 动作描述/场景叙述:
   {{type:"action", text:"李浮尘走进大殿。", is_forced:false, is_centered:false}}

2. dialogue_block — 对白逻辑块（聚合角色名+括号指示+台词）:
   {{type:"dialogue_block", character_id:"char_01", character_name:"李浮尘",
    parenthetical:"(冷笑)", dialogue:"你不是我对手。", is_dual:false}}
   - character_extension 用于 (V.O.)/(O.S.) 等标记，可选
   - parenthetical 是可选的表情/动作指示，必须以 ( 开头 ) 结尾

3. transition — 转场指示:
   {{type:"transition", text:"CUT TO:"}}

4. lyric — 歌词/诗句:
   {{type:"lyric", text:"星空下的低语..."}}

重要：对白必须使用 dialogue_block 类型，切勿拆分为 character + dialogue + parenthetical 三个独立元素。

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
5. 仅在原文的叙述性描写需要转换为对白时，才可创建新的 dialogue_block 元素
6. 创建的新对白必须在 source_ref 中标记 confidence: "inferred"

=== 一般规则 ===
对白使用 dialogue_block 类型，去除小说化描写，心理活动转换为 action 或 dialogue_block。
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

    raw: object = None
    try:
        raw = invoke_with_retry(chain, prompt_inputs, "scene_conversion")
        result = SceneList.model_validate(raw) if isinstance(raw, dict) else raw
        scenes = _inject_source_refs(result.scenes, chapter)
        logger.info("Chapter %d converted to %d scene(s).", chapter.index, len(scenes))
        return scenes
    except Exception as exc:
        logger.warning(
            "Converter failed for chapter %d — attempting per-scene rescue: %s",
            chapter.index, exc,
        )
        # The LLM may return elements in old flat format that the field_validator
        # can coerce per-scene even if full SceneList validation failed.
        if isinstance(raw, dict) and "scenes" in raw:
            rescued = []
            for sd in raw["scenes"]:
                try:
                    rescued.append(Scene.model_validate(sd))
                except Exception:
                    continue
            if rescued:
                scenes = _inject_source_refs(rescued, chapter)
                logger.info(
                    "Chapter %d: rescued %d/%d scene(s).",
                    chapter.index, len(scenes), len(raw["scenes"]),
                )
                return scenes
        return []


def _summarize_kg(kg: KnowledgeGraph) -> str:
    if not kg.nodes:
        return "（知识图谱为空）"
    lines = ["【知识图谱】"]
    for n in [n for n in kg.nodes if n.type == "character"]:
        aliases = n.metadata.get("aliases", [])
        alias_str = f" (别名: {', '.join(aliases)})" if aliases else ""
        lines.append(f"  {n.id}: {n.label}{alias_str}")
    for n in [n for n in kg.nodes if n.type == "location"]:
        lines.append(f"  {n.id}: {n.label}")
    for e in kg.edges:
        lines.append(f"  {e.source} --[{e.relation}]--> {e.target}")
    return "\n".join(lines)


def _elem_text(elem: ScriptElement) -> str:
    """Extract searchable text from any element type for source_ref matching."""
    if isinstance(elem, ActionElement):
        return elem.text
    elif isinstance(elem, DialogueBlock):
        return elem.dialogue
    else:
        return getattr(elem, "text", "") or getattr(elem, "dialogue", "")


def _inject_source_refs(scenes: list[Scene], chapter: Chapter) -> list[Scene]:
    chapter_len = len(chapter.text)
    total_elements = sum(len(s.elements) for s in scenes)
    elem_seq = 0
    for scene in scenes:
        for elem in scene.elements:
            if elem.source_ref is not None:
                elem_seq += 1
                continue
            content = _elem_text(elem)
            if not content:
                elem_seq += 1
                continue
            pos = chapter.text.find(content)
            match_type = "exact"
            if pos == -1:
                prefix = content[:10] if len(content) >= 10 else content
                pos = chapter.text.find(prefix)
                if pos != -1:
                    match_type = "prefix"
            if pos != -1:
                offset_start, offset_end = pos, pos + len(content)
            else:
                ratio = elem_seq / max(total_elements, 1)
                offset_start, offset_end = int(chapter_len * ratio), int(chapter_len * ratio) + len(content)
            elem.source_ref = SourceRef(
                chapter_id=f"ch_{chapter.index:02d}",
                offset=[offset_start, offset_end],
                confidence=match_type if pos != -1 else "estimated",
            )
            elem_seq += 1
    return scenes
