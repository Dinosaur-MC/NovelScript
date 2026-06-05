"""GraphRAG builder — extracts a Knowledge Graph from novel chapters.

Uses LangChain-native ChatPromptTemplate + with_structured_output()
for schema-validated extraction.
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from cli.llm_router import get_llm
from cli.models import Chapter, KnowledgeGraph

logger = logging.getLogger(__name__)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个知识图谱提取专家。从小说文本中提取实体及其关系。

实体类型: character, location, item, event, organization
关系类型: friend_of, enemy_of, master_of, subordinate_of, family_of, lover_of, located_in, belongs_to, owns, used_by, participates_in, causes, leads_to

每个实体必须有唯一的 id (n_01, n_02, ...)。人物实体的 properties 中必须包含 aliases (数组) 和 traits (数组)。
关系权重 weight 在 0.0 到 1.0 之间。只提取明确在文本中出现或强烈暗示的实体和关系。"""),
    ("human", "请从以下小说文本中提取知识图谱：\n\n{text}"),
])


def extract_graph(chapters: list[Chapter]) -> KnowledgeGraph:
    if not chapters:
        logger.warning("No chapters provided — returning empty KnowledgeGraph.")
        return KnowledgeGraph()

    combined = "\n\n".join(
        f"【{ch.title}】\n{ch.text[:6000]}" for ch in chapters
    )[:24000]

    llm = get_llm("global_extraction", temperature=0.3)
    structured_llm = llm.with_structured_output(KnowledgeGraph)

    try:
        kg: KnowledgeGraph = structured_llm.invoke(
            _PROMPT.invoke({"text": combined})
        )
        logger.info("GraphRAG: extracted %d node(s), %d edge(s).",
                     len(kg.nodes), len(kg.edges))
        return kg
    except Exception as exc:
        logger.exception("GraphRAG extraction failed: %s", exc)
        return KnowledgeGraph()
