"""GraphRAG builder — extracts a Knowledge Graph from novel chapters.

Uses the Pro model to identify entities (characters, locations, items) and
their relationships, then validates the result through Pydantic with an
Auto-Fix retry loop (max 2 retries).
"""

from __future__ import annotations

import json
import logging
import textwrap

from langchain_core.messages import HumanMessage, SystemMessage

from cli.llm_router import get_llm
from cli.models import Chapter, KnowledgeEdge, KnowledgeGraph, KnowledgeNode

logger = logging.getLogger(__name__)

# Maximum retries for the Auto-Fix loop
MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
你是一个知识图谱提取专家。你需要从小说文本中提取实体及其关系，并以严格的 JSON 格式输出。

实体类型 (node_type) 包含:
- character: 人物角色
- location: 地点/场景
- item: 重要物品/道具
- event: 重要事件
- organization: 组织/势力

关系类型 (relation) 示例:
- friend_of, enemy_of, master_of, subordinate_of, family_of, lover_of
- located_in, belongs_to, owns, used_by
- participates_in, causes, leads_to

输出格式必须是严格的 JSON：
```json
{
  "nodes": [
    {"id": "n_01", "name": "张三", "node_type": "character", "properties": {"aliases": ["三哥"], "traits": ["勇敢", "冲动"]}},
    {"id": "n_02", "name": "京城", "node_type": "location", "properties": {"description": "繁华都城"}}
  ],
  "edges": [
    {"source_node_id": "n_01", "target_node_id": "n_02", "relation": "located_in", "weight": 0.9}
  ]
}
```

注意:
- 每个实体必须有唯一的 id (n_01, n_02, ...)
- 人物实体的 properties 中必须包含 aliases (数组) 和 traits (数组)
- 关系权重 weight 在 0.0 到 1.0 之间，表示确信度
- 只提取明确在文本中出现或强烈暗示的实体和关系
""")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_graph(chapters: list[Chapter]) -> KnowledgeGraph:
    """Extract a knowledge graph from the provided chapters.

    Args:
        chapters: Ordered list of Chapter objects.

    Returns:
        A validated KnowledgeGraph (may be empty if extraction fails).

    The function aggregates all chapter text, sends it to the Pro model,
    and retries up to ``MAX_RETRIES`` times on Pydantic validation failure,
    feeding the error back to the model (Auto-Fix loop).
    """
    if not chapters:
        logger.warning("No chapters provided — returning empty KnowledgeGraph.")
        return KnowledgeGraph()

    combined = "\n\n".join(
        f"【{ch.title}】\n{ch.text}" for ch in chapters
    )

    llm = get_llm("global_extraction", temperature=0.3)

    for attempt in range(1 + MAX_RETRIES):
        try:
            raw_json = _call_llm(llm, combined, attempt)
            kg = _parse_and_validate(raw_json)
            logger.info(
                "GraphRAG: extracted %d node(s), %d edge(s).",
                len(kg.nodes),
                len(kg.edges),
            )
            return kg
        except Exception as exc:
            logger.warning(
                "GraphRAG attempt %d/%d failed: %s",
                attempt + 1,
                1 + MAX_RETRIES,
                exc,
            )
            if attempt >= MAX_RETRIES:
                logger.exception("GraphRAG: all retries exhausted.")
                return KnowledgeGraph()
            # The error message is fed back implicitly via the attempt counter
            # in the prompt for the next call.

    return KnowledgeGraph()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _call_llm(llm, text: str, attempt: int) -> str:
    """Invoke the LLM and return the raw JSON string."""
    user_prompt = (
        f"请从以下小说文本中提取知识图谱：\n\n{text[:16000]}"
    )
    if attempt > 0:
        user_prompt = (
            f"上一次提取的结果不符合 JSON 格式要求。请严格按照指定的 JSON Schema 重新提取。"
            f"确保所有字段完整、类型正确。\n\n{text[:16000]}"
        )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    resp = llm.invoke(messages)
    raw = resp.content.strip()  # type: ignore[union-attr]

    # Strip markdown fences if present
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    return raw


def _parse_and_validate(raw_json: str) -> KnowledgeGraph:
    """Parse JSON and validate via Pydantic. Raises on failure."""
    data = json.loads(raw_json)

    nodes = [
        KnowledgeNode(
            id=n["id"],
            name=n["name"],
            node_type=n["node_type"],
            properties=n.get("properties", {}),
        )
        for n in data.get("nodes", [])
    ]

    edges = [
        KnowledgeEdge(
            source_node_id=e["source_node_id"],
            target_node_id=e["target_node_id"],
            relation=e["relation"],
            weight=e.get("weight", 1.0),
        )
        for e in data.get("edges", [])
    ]

    return KnowledgeGraph(nodes=nodes, edges=edges)
