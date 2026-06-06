"""GraphRAG builder — extracts a Knowledge Graph from novel chapters.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).

When a FAISS index is provided, each chapter's RAG search results are
injected as cross-chapter context, helping the LLM discover entities
and relations that span multiple chapters.
"""

from __future__ import annotations

import logging
from typing import Optional

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
    ("human", """\
请从以下小说文本中提取知识图谱，以 JSON 格式输出：

{rag_context}
【待提取小说文本】
{text}"""),
])


def extract_graph(
    chapters: list[Chapter],
    faiss_index=None,
    all_chapter_texts: list[str] | None = None,
) -> KnowledgeGraph:
    """Extract a KnowledgeGraph from *chapters*.

    Args:
        chapters:         Ordered chapter list.
        faiss_index:      Optional FAISS vector store.  When provided,
                          each chapter's opening text is used as a
                          query to retrieve related content from other
                          chapters — this helps the LLM find cross-
                          chapter entities and relations.
        all_chapter_texts: Fallback texts for keyword search when the
                          FAISS index is unavailable.
    """
    if not chapters:
        logger.warning("No chapters provided — returning empty KnowledgeGraph.")
        return KnowledgeGraph()

    combined = "\n\n".join(
        f"【{ch.title}】\n{ch.text[:6000]}" for ch in chapters
    )[:24000]

    # Build cross-chapter RAG context
    rag_context = _build_rag_context(chapters, faiss_index, all_chapter_texts)

    llm = get_llm("global_extraction", temperature=0.3, json_mode=True)
    chain = _PROMPT | llm | _parser

    try:
        raw = chain.invoke({
            "text": combined,
            "rag_context": rag_context,
            "format_instructions": _parser.get_format_instructions(),
        })
        kg = KnowledgeGraph.model_validate(raw) if isinstance(raw, dict) else raw
        logger.info("GraphRAG: extracted %d node(s), %d edge(s).",
                     len(kg.nodes), len(kg.edges))
        return kg
    except Exception as exc:
        logger.exception("GraphRAG extraction failed: %s", exc)
        return KnowledgeGraph()


def _build_rag_context(
    chapters: list[Chapter],
    faiss_index,
    all_chapter_texts: list[str] | None,
) -> str:
    """Build a cross-chapter context block from RAG search results.

    Each chapter's first ~200 characters are used as a query.  The
    top 2 related passages from *other* chapters are collected and
    deduplicated.
    """
    if faiss_index is None and not all_chapter_texts:
        return ""

    from cli.rag_builder import search

    texts = all_chapter_texts or []
    seen: set[str] = set()
    passages: list[str] = []

    for ch in chapters:
        query = ch.text[:200]
        results = search(
            faiss_index, query, k=3,
            fallback_texts=texts,
        )
        for r in results:
            # Skip passages that are just the query chapter itself
            if r[:50].strip() == ch.text[:50].strip():
                continue
            key = r[:80]  # dedup by first 80 chars
            if key not in seen:
                seen.add(key)
                # Keep each passage reasonably short
                passages.append(r[:400])

    if not passages:
        return ""

    # Limit total context size
    ctx_lines = ["【跨章节语义关联上下文（来自 RAG 检索）】"]
    total = 0
    for p in passages:
        trunc = p[:400]
        ctx_lines.append(f"- {trunc}")
        total += len(trunc)
        if total > 3000:
            break

    logger.debug("RAG context for GraphRAG: %d passage(s), %d chars.",
                 len(ctx_lines) - 1, total)
    return "\n".join(ctx_lines) + "\n\n"
