"""GraphRAG service — KG-enhanced context builder + LangGraph patch generation.

Provides:
1. ``build_graph_context()`` — injects relevant KG context into AI prompts.
2. ``create_patch_workflow()`` — LangGraph-based workflow that generates
   structured JSON Patch via tool calling instead of fragile regex.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from sqlalchemy.orm import Session
from sqlalchemy import select, text as sa_text

from app.models.sql import KnowledgeEdge, KnowledgeNode, Script
from cli.llm_router import get_llm, invoke_llm_with_retry

logger = logging.getLogger(__name__)


# ===========================================================================
# GraphRAG Context Builder
# ===========================================================================


def build_graph_context(
    db: Session,
    novel_id: str | None,
    script_id: str,
    query: str,
    max_nodes: int = 20,
) -> str:
    """Return relevant KG context for a chat query.

    Searches the knowledge graph for nodes matching *query* keywords
    and returns a formatted string of matching entities and relations.

    Falls back to returning all nodes if the query is empty.
    """
    if not novel_id and not script_id:
        return ""

    # Extract keywords from query (simple Chinese/English word splitting)
    keywords = _extract_keywords(query)
    lines: list[str] = ["## Knowledge Graph Context"]

    # Build node query
    stmt = select(KnowledgeNode)
    if script_id:
        # Script-level KG takes priority
        stmt = stmt.where(KnowledgeNode.script_id == script_id)
    elif novel_id:
        stmt = stmt.where(KnowledgeNode.novel_id == novel_id)

    nodes = db.execute(stmt).scalars().all()

    if not nodes:
        lines.append("No knowledge graph data available for this script.")
        return "\n".join(lines)

    # Score nodes by keyword relevance
    scored = []
    for n in nodes:
        score = 0
        name_lower = n.name.lower()
        desc_lower = (n.description or "").lower()
        aliases_lower = [a.lower() for a in (n.aliases or [])]

        for kw in keywords:
            if kw in name_lower:
                score += 5
            if kw in desc_lower:
                score += 3
            for a in aliases_lower:
                if kw in a:
                    score += 4
        scored.append((score, n))

    # Sort by relevance, take top N
    scored.sort(key=lambda x: -x[0])
    top_nodes = [n for _, n in scored[:max_nodes]]

    # Format nodes
    lines.append(f"\n### Entities ({len(top_nodes)} relevant)")
    for n in top_nodes:
        aliases_str = f" (别名: {', '.join(n.aliases)})" if n.aliases else ""
        desc_str = f" — {n.description[:200]}" if n.description else ""
        lines.append(f"- **{n.name}** [{n.node_type}]{aliases_str}{desc_str}")

    # Find edges connecting top nodes
    node_ids = [n.id for n in top_nodes]
    if node_ids:
        edge_stmt = select(KnowledgeEdge).where(
            KnowledgeEdge.source_node_id.in_(node_ids),
            KnowledgeEdge.target_node_id.in_(node_ids),
        )
        edges = db.execute(edge_stmt).scalars().all()

        if edges:
            node_map = {str(n.id): n for n in top_nodes}
            lines.append(f"\n### Relations ({len(edges)} edges)")
            for e in edges[:30]:  # limit to 30 edges
                src = node_map.get(str(e.source_node_id))
                tgt = node_map.get(str(e.target_node_id))
                if src and tgt:
                    weight_str = f" (权重: {e.weight:.1f})" if e.weight != 1.0 else ""
                    lines.append(f"- {src.name} --[{e.relation}]--> {tgt.name}{weight_str}")

    return "\n".join(lines)


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a query string.

    Splits on whitespace/punctuation and filters out short/common words.
    """
    import re
    # Split on whitespace and Chinese punctuation
    tokens = re.split(r"[\s,，。、；;：:！？!?()（）【】\[\]]+", text)
    keywords = []
    for t in tokens:
        t = t.strip()
        if len(t) >= 1:  # Keep single Chinese chars too
            keywords.append(t.lower())
    return keywords


# ===========================================================================
# LangGraph Patch Workflow
# ===========================================================================

# ── Tool Definitions ──────────────────────────────────────────────────────


@tool
def apply_script_patch(
    op: str,
    path: str,
    value: Any,
    reasoning: str = "",
) -> str:
    """Apply a JSON Patch operation to the script document.

    Call this tool when you want to make a concrete change to the script.
    The patch will be validated and applied to the script JSON document.

    Args:
        op: The patch operation type. Must be one of: "replace", "add", "remove".
        path: RFC 6901 JSON Pointer path. Examples:
            - "/scenes/0/title" — change scene title
            - "/scenes/0/elements/0/dialogue" — change dialogue text
            - "/characters/0/name" — rename a character
        value: The new value (required for "replace" and "add", omitted for "remove").
        reasoning: Brief explanation of why this change is being made.
    """
    # This function is the tool definition — the actual application is
    # handled by the workflow's tool executor.
    return json.dumps({"op": op, "path": path, "value": value, "reasoning": reasoning}, ensure_ascii=False)


# ── Workflow State ────────────────────────────────────────────────────────


class PatchState(MessagesState):
    """State for the patch generation workflow."""
    patch_result: Optional[dict] = None


# ── Node Functions ────────────────────────────────────────────────────────


def call_llm_with_tools(state: PatchState) -> dict:
    """Call the LLM with available tools and return the response."""
    messages = state["messages"]
    llm = get_llm("ai_chat", temperature=0.3)
    llm_with_tools = llm.bind_tools([apply_script_patch])
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def apply_tool_call(state: PatchState) -> dict:
    """Extract the tool call result from the LLM response."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            if tc.get("name") == "apply_script_patch":
                args = tc.get("args", {})
                return {
                    "patch_result": {
                        "op": args.get("op"),
                        "path": args.get("path"),
                        "value": args.get("value"),
                        "reasoning": args.get("reasoning", ""),
                    }
                }
    return {"patch_result": None}


def should_continue(state: PatchState) -> str:
    """Determine if we should continue or end."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "apply_tool"
    return END


# ── Build Workflow ────────────────────────────────────────────────────────


def create_patch_workflow() -> StateGraph:
    """Create a LangGraph workflow for AI patch generation.

    Returns a compiled StateGraph that processes chat messages and
    optionally produces a structured JSON Patch.

    Usage::

        workflow = create_patch_workflow()
        result = workflow.invoke({
            "messages": [
                SystemMessage(content="..."),
                HumanMessage(content="change the title"),
            ]
        })
        patch = result.get("patch_result")
    """
    workflow = StateGraph(PatchState)

    workflow.add_node("llm", call_llm_with_tools)
    workflow.add_node("apply_tool", apply_tool_call)

    workflow.set_entry_point("llm")
    workflow.add_conditional_edges("llm", should_continue, {
        "apply_tool": "apply_tool",
        END: END,
    })
    workflow.add_edge("apply_tool", END)

    return workflow.compile()


# ── Convenience ───────────────────────────────────────────────────────────


# Singleton workflow instance (compiled once)
_patch_workflow = None


def get_patch_workflow():
    """Return the compiled LangGraph patch workflow (cached singleton)."""
    global _patch_workflow
    if _patch_workflow is None:
        _patch_workflow = create_patch_workflow()
    return _patch_workflow


def generate_patch_with_langgraph(
    system_prompt: str,
    user_message: str,
) -> tuple[str, Optional[dict]]:
    """Generate a chat reply + optional JSON Patch using LangGraph workflow.

    Returns:
        ``(reply_text, patch_dict_or_None)``
    """
    workflow = get_patch_workflow()
    result = workflow.invoke({
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ],
    })

    # Extract reply text (last non-tool message)
    reply = ""
    patch = result.get("patch_result")

    for msg in result.get("messages", []):
        if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
            reply = msg.content

    return reply, patch
