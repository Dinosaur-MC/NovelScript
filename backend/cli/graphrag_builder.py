"""GraphRAG builder — extracts a Knowledge Graph from novel chapters.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).
"""

from __future__ import annotations

import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from cli.llm_router import get_llm
from cli.models import Chapter, KnowledgeGraph

logger = logging.getLogger(__name__)

_parser = JsonOutputParser(pydantic_object=KnowledgeGraph)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个知识图谱提取专家。从小说文本中提取实体及其关系。

实体类型: character, location, item, event, organization
关系类型: friend_of, enemy_of, master_of, subordinate_of, family_of, lover_of, located_in, belongs_to, owns, used_by, participates_in, causes, leads_to

每个实体必须有唯一的 id (n_01, n_02, ...)。人物实体的 properties 中必须包含 aliases (数组) 和 traits (数组)。
关系权重 weight 在 0.0 到 1.0 之间。只提取明确在文本中出现或强烈暗示的实体和关系。

{format_instructions}"""),
    ("human", "请从以下小说文本中提取知识图谱，以 JSON 格式输出：\n\n{text}"),
])


def extract_graph(chapters: list[Chapter]) -> KnowledgeGraph:
    if not chapters:
        logger.warning("No chapters provided — returning empty KnowledgeGraph.")
        return KnowledgeGraph()

    combined = "\n\n".join(
        f"【{ch.title}】\n{ch.text[:6000]}" for ch in chapters
    )[:24000]

    llm = get_llm("global_extraction", temperature=0.3, json_mode=True)
    chain = _PROMPT | llm | _parser

    try:
        raw = chain.invoke({
            "text": combined,
            "format_instructions": _parser.get_format_instructions(),
        })
        kg = KnowledgeGraph.model_validate(raw) if isinstance(raw, dict) else raw
        logger.info("GraphRAG: extracted %d node(s), %d edge(s).",
                     len(kg.nodes), len(kg.edges))
        return kg
    except Exception as exc:
        logger.exception("GraphRAG extraction failed: %s", exc)
        return KnowledgeGraph()
