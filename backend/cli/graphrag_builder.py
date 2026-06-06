"""GraphRAG builder — extracts a Knowledge Graph from novel chapters.

Uses LangChain-native ChatPromptTemplate + JsonOutputParser with
DeepSeek native JSON mode (``response_format: {type: json_object}``).

Two extraction modes
--------------------
1. **Single-shot** (``extract_graph``) — all chapters in one prompt.
   Fast for short novels (≤10 chapters) but may miss cross-chapter
   entity deduplication at scale.

2. **Incremental** (``extract_graph_incremental``) — chapters processed
   sequentially, each inheriting previously extracted entities as
   context.  Scales to 100+ chapter novels; enables natural entity
   deduplication and per-chapter DB persistence.

When a FAISS index is provided, each chapter's RAG search results are
injected as cross-chapter context, helping the LLM discover entities
and relations that span multiple chapters.

Input text is sliced by paragraph-aligned groups (not raw character
counts), using the model's context budget from ``context_chars()``.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from cli.llm_router import context_chars, get_llm, invoke_with_retry
from cli.models import Chapter, KnowledgeGraph
from cli.paragraph_splitter import split_paragraphs

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
        faiss_index:      Optional FAISS vector store for RAG.
        all_chapter_texts: Fallback texts for keyword search.
    """
    if not chapters:
        logger.warning("No chapters provided — returning empty KnowledgeGraph.")
        return KnowledgeGraph()

    # Build chapter text from paragraph-aligned groups
    budget = context_chars("global_extraction")
    per_chapter_budget = max(5000, budget // max(len(chapters), 1))
    sections: list[str] = []
    for ch in chapters:
        groups = split_paragraphs(ch.text, max_chars=per_chapter_budget)
        section = groups[0].text if groups else ch.text[:per_chapter_budget]
        sections.append(f"【{ch.title}】\n{section}")

    # Still apply a combined cap in case of extreme chapter count
    combined = "\n\n".join(sections)
    if len(combined) > budget:
        combined = combined[:budget]
        logger.info("GraphRAG text capped at %d chars (budget for stage).", budget)

    # Build cross-chapter RAG context
    rag_context = _build_rag_context(chapters, faiss_index, all_chapter_texts)

    llm = get_llm("global_extraction", temperature=0.3, json_mode=True)
    chain = _PROMPT | llm | _parser

    try:
        raw = invoke_with_retry(chain, {
            "text": combined,
            "rag_context": rag_context,
            "format_instructions": _parser.get_format_instructions(),
        }, "global_extraction")
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
    """Build a cross-chapter context block from RAG search results."""
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
            if r[:50].strip() == ch.text[:50].strip():
                continue
            key = r[:80]
            if key not in seen:
                seen.add(key)
                passages.append(r[:400])

    if not passages:
        return ""

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


# =============================================================================
# Incremental extraction — chapter-by-chapter with prior-entity context
# =============================================================================

_INCREMENTAL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个知识图谱提取专家。从小说文本中提取实体及其关系。

实体类型: character, location, item, event, organization
关系类型: friend_of, enemy_of, master_of, subordinate_of, family_of, lover_of, located_in, belongs_to, owns, used_by, participates_in, causes, leads_to

每个实体必须有唯一的 id。人物实体的 properties 中必须包含 aliases (数组) 和 traits (数组)。
关系权重 weight 在 0.0 到 1.0 之间。只提取明确在文本中出现或强烈暗示的实体和关系。

{prior_entities}

{format_instructions}"""),
    ("human", """\
请从以下小说文本中提取知识图谱，以 JSON 格式输出：

{rag_context}
【待提取小说文本 — {chapter_label}】
{text}"""),
])


def _format_prior_entities(kg: KnowledgeGraph) -> str:
    """Build a compact reference block of already-extracted entities.

    Returns an empty string when *kg* is empty so the system prompt reads
    naturally (no "Prior entities:" header with nothing under it).
    """
    if not kg.nodes:
        return ""

    lines = ["【已提取的实体（如果以下实体再次出现，请复用相同的 id）】"]
    for n in kg.nodes:
        aliases = n.properties.get("aliases", [])
        alias_hint = f" 别名: {', '.join(aliases[:5])}" if aliases else ""
        lines.append(f"  {n.id}: {n.name} ({n.node_type}){alias_hint}")
    return "\n".join(lines) + "\n"


def _merge_kg(accumulated: KnowledgeGraph, incoming: KnowledgeGraph) -> KnowledgeGraph:
    """Merge *incoming* nodes/edges into *accumulated*, deduplicating by name.

    When an incoming node has the same *name* and *node_type* as an existing
    node, the existing id is preferred and the incoming node's aliases/traits
    are merged into the existing properties.  Edges referencing the old id
    are re-pointed.
    """
    # Build lookup: (name, node_type) → accumulated node id
    name_map: dict[tuple[str, str], str] = {}
    for n in accumulated.nodes:
        name_map[(n.name, n.node_type)] = n.id
        for alias in n.properties.get("aliases", []):
            name_map[(alias, n.node_type)] = n.id

    # Map incoming ids → merged ids (could be an accumulated id)
    id_map: dict[str, str] = {}

    for n in incoming.nodes:
        key = (n.name, n.node_type)
        if key in name_map:
            # Reuse existing id; merge aliases/traits
            id_map[n.id] = name_map[key]
            existing = next(
                (en for en in accumulated.nodes if en.id == name_map[key]), None
            )
            if existing:
                _merge_node_properties(existing, n)
        else:
            # New entity — keep its id, add to accumulated
            id_map[n.id] = n.id
            name_map[key] = n.id
            accumulated.nodes.append(n)

    # Merge edges, re-pointing source/target to resolved ids
    seen_edges: set[tuple[str, str, str]] = set()
    for e in accumulated.edges:
        seen_edges.add((e.source_node_id, e.target_node_id, e.relation))
    for e in incoming.edges:
        src = id_map.get(e.source_node_id, e.source_node_id)
        tgt = id_map.get(e.target_node_id, e.target_node_id)
        key = (src, tgt, e.relation)
        if key not in seen_edges:
            seen_edges.add(key)
            e.source_node_id = src
            e.target_node_id = tgt
            accumulated.edges.append(e)

    return accumulated


def _merge_node_properties(existing: KnowledgeNode, incoming: KnowledgeNode) -> None:
    """Merge *incoming* aliases and traits into *existing* (in-place)."""
    existing_aliases: list[str] = existing.properties.get("aliases", [])
    incoming_aliases: list[str] = incoming.properties.get("aliases", [])
    for a in incoming_aliases:
        if a not in existing_aliases:
            existing_aliases.append(a)
    existing.properties["aliases"] = existing_aliases

    existing_traits: list[str] = existing.properties.get("traits", [])
    incoming_traits: list[str] = incoming.properties.get("traits", [])
    for t in incoming_traits:
        if t not in existing_traits:
            existing_traits.append(t)
    existing.properties["traits"] = existing_traits

    # Merge top-level properties that aren't aliases/traits
    for k, v in incoming.properties.items():
        if k in ("aliases", "traits"):
            continue
        if k not in existing.properties:
            existing.properties[k] = v


def extract_graph_incremental(
    chapters: list[Chapter],
    faiss_index=None,
    all_chapter_texts: list[str] | None = None,
) -> KnowledgeGraph:
    """Extract a KnowledgeGraph chapter-by-chapter, accumulating state.

    Each chapter's extraction inherits the entity IDs from prior chapters
    so the LLM can reuse them for the same characters/locations.  This
    scales naturally to novels with 100+ chapters without exceeding
    context-window limits.

    Args:
        chapters:          Ordered chapter list.
        faiss_index:       Optional FAISS vector store for RAG.
        all_chapter_texts: Fallback texts for keyword search.

    Returns:
        A merged KnowledgeGraph covering all chapters.
    """
    if not chapters:
        return KnowledgeGraph()

    accumulated = KnowledgeGraph()
    budget = context_chars("global_extraction")

    for ch in chapters:
        # Build paragraph-aligned text for this chapter
        groups = split_paragraphs(ch.text, max_chars=budget)
        chapter_text = groups[0].text if groups else ch.text[:budget]

        # Build RAG context for this chapter (cross-chapter clues)
        rag_context = _build_rag_context([ch], faiss_index, all_chapter_texts)

        # Build prior-entity reference
        prior_block = _format_prior_entities(accumulated)

        llm = get_llm("global_extraction", temperature=0.3, json_mode=True)
        chain = _INCREMENTAL_PROMPT | llm | _parser

        chapter_label = f"{ch.title or '未知章节'} (第{ch.index + 1}章)"

        try:
            raw = invoke_with_retry(chain, {
                "text": chapter_text,
                "rag_context": rag_context,
                "prior_entities": prior_block,
                "chapter_label": chapter_label,
                "format_instructions": _parser.get_format_instructions(),
            }, "global_extraction")
            chapter_kg = (
                KnowledgeGraph.model_validate(raw)
                if isinstance(raw, dict) else raw
            )
            accumulated = _merge_kg(accumulated, chapter_kg)
            logger.info(
                "GraphRAG ch.%d: extracted %d node(s), %d edge(s) "
                "(accumulated: %d nodes, %d edges).",
                ch.index, len(chapter_kg.nodes), len(chapter_kg.edges),
                len(accumulated.nodes), len(accumulated.edges),
            )
        except Exception as exc:
            logger.exception(
                "GraphRAG extraction failed for chapter %d: %s — continuing.",
                ch.index, exc,
            )
            # Continue with next chapter; don't lose accumulated state

    logger.info(
        "GraphRAG incremental complete: %d node(s), %d edge(s) across %d chapter(s).",
        len(accumulated.nodes), len(accumulated.edges), len(chapters),
    )
    return accumulated
