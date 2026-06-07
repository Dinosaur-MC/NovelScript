"""AI editor / chat API — real-time AI-assisted script editing.

Routes (script-centric, task routes kept for backward compat)
------
POST /chat/{script_id}        — Send a chat message; optionally get a JSON Patch back.
POST /apply_patch/{script_id} — Apply a JSON Patch to the script's script_json.
POST /undo/{script_id}        — Roll back the most recent patch operation.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from cli.llm_router import get_llm, invoke_llm_with_retry

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import (
    Dialogue,
    KnowledgeEdge,
    KnowledgeNode,
    Operation,
    Script,
    Task,
    User,
)
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)


def _parse_task_id(task_id: str) -> uuid.UUID:
    """Parse and validate a task_id string, raising 400 on invalid UUID."""
    try:
        return uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid task_id: {task_id!r}")

router = APIRouter(prefix="/editor", tags=["Editor"])

# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

task_crud = BaseCRUD[Task](Task)
dialogue_crud = BaseCRUD[Dialogue](Dialogue)
operation_crud = BaseCRUD[Operation](Operation)

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Incoming chat message with optional scene targeting."""

    message: str = Field(..., min_length=1, description="User message text")
    scene_id: Optional[str] = Field(
        None, description="Optional scene identifier for context injection"
    )


class PatchRequest(BaseModel):
    """A single JSON Patch operation for apply_patch."""

    op: str = Field(..., description="Patch operation: add, remove, or replace")
    path: str = Field(..., description="JSON Pointer target path, e.g. /characters/0/name")
    value: Any = Field(..., description="Value to apply (required for add / replace)")


# ---------------------------------------------------------------------------
# JSON Pointer helpers (RFC 6901)
# ---------------------------------------------------------------------------


def _parse_json_pointer(path: str) -> list[str]:
    """Parse an RFC 6901 JSON Pointer into path segments.

    >>> _parse_json_pointer("/a/b")
    ['a', 'b']
    >>> _parse_json_pointer("/a/0")
    ['a', '0']
    >>> _parse_json_pointer("/a~1b")
    ['a/b']
    """
    if not path.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'")
    if path == "/":
        return [""]
    parts = path[1:].split("/")
    return [p.replace("~1", "/").replace("~0", "~") for p in parts]


def _navigate_to_parent(obj: dict | list, segments: list[str]):
    """Walk *segments* to return ``(parent_container, last_key)``.

    *last_key* is an ``int`` when the parent is a list, otherwise ``str``.
    """
    current: Any = obj
    for seg in segments[:-1]:
        if isinstance(current, list):
            idx = int(seg)
            if idx < 0 or idx >= len(current):
                raise IndexError(f"List index {idx} out of range (len={len(current)})")
            current = current[idx]
        else:
            if seg not in current:
                raise KeyError(f"Key {seg!r} not found in object")
            current = current[seg]
    last = segments[-1]
    if isinstance(current, list):
        return current, int(last)
    return current, last


def _apply_patch_op(obj: dict, op: str, path: str, value: Any) -> dict:
    """Apply a single RFC-6902-style operation to *obj* (mutates in place).

    Supported operations: ``replace``, ``add``, ``remove``.
    """
    segments = _parse_json_pointer(path)

    if op == "replace":
        container, key = _navigate_to_parent(obj, segments)
        if isinstance(container, list):
            if key < 0 or key >= len(container):
                raise IndexError(f"Replace index {key} out of range")
            container[key] = value
        else:
            if key not in container:
                raise KeyError(f"Replace key {key!r} not found")
            container[key] = value

    elif op == "add":
        container, key = _navigate_to_parent(obj, segments)
        if isinstance(container, list):
            container.insert(key, value)
        else:
            container[key] = value

    elif op == "remove":
        container, key = _navigate_to_parent(obj, segments)
        if isinstance(container, list):
            if key < 0 or key >= len(container):
                raise IndexError(f"Remove index {key} out of range")
            container.pop(key)
        else:
            if key not in container:
                raise KeyError(f"Remove key {key!r} not found")
            del container[key]

    else:
        raise ValueError(f"Unsupported patch operation: {op!r}")

    return obj


def _get_at_path(obj: dict, path: str) -> Any:
    """Retrieve the value at a JSON Pointer *path*."""
    segments = _parse_json_pointer(path)
    current: Any = obj
    for seg in segments:
        if isinstance(current, list):
            current = current[int(seg)]
        else:
            current = current[seg]
    return current


# ---------------------------------------------------------------------------
# JSON Patch extraction from AI replies
# ---------------------------------------------------------------------------


def _find_json_objects(text: str) -> list[str]:
    """Find balanced-brace JSON object substrings in *text*."""
    results: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            j = i
            in_string = False
            escape = False
            while j < len(text):
                c = text[j]
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = not in_string
                elif not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            results.append(text[i : j + 1])
                            break
                j += 1
        i += 1
    return results


def _extract_json_patch(text: str) -> Optional[dict]:
    """Try to extract a JSON Patch object from AI reply text.

    Looks for JSON objects that contain ``"op"`` and ``"path"`` keys,
    preferring those inside markdown code fences (`````json … ``` ``).
    """
    # -- 1. Markdown code fences (```json … ``` or ``` … ```) ---------------
    fence_re = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
    for match in fence_re.finditer(text):
        block = match.group(1).strip()
        for candidate in _find_json_objects(block):
            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "op" in obj and "path" in obj:
                logger.debug("Extracted JSON patch from code fence: %s", obj)
                return obj

    # -- 2. Anywhere in the text --------------------------------------------
    for candidate in _find_json_objects(text):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "op" in obj and "path" in obj:
            logger.debug("Extracted JSON patch from inline: %s", obj)
            return obj

    return None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_graph_context(
    db: Session,
    task_id: uuid.UUID,
    user_message: str,
) -> str:
    """Query the knowledge graph for entities mentioned in *user_message*.

    Returns a compact text block listing matched entities and their 1-hop
    neighbours (via ``knowledge_edges``), or an empty string when no KG
    data exists for this task.
    """
    # Find all node names that appear as substrings in the user message
    stmt = db.query(KnowledgeNode).filter(
        KnowledgeNode.task_id == task_id,
    )
    all_nodes = stmt.all()
    if not all_nodes:
        return ""

    # Match: case-insensitive substring check
    msg_lower = user_message.lower()
    matched_ids: set[uuid.UUID] = set()
    for n in all_nodes:
        if n.name.lower() in msg_lower:
            matched_ids.add(n.id)
        for alias in n.aliases or []:
            if alias.lower() in msg_lower:
                matched_ids.add(n.id)
                break

    if not matched_ids:
        return ""

    # Gather matched entities + 1-hop neighbours
    neighbour_ids: set[uuid.UUID] = set()
    edge_stmt = db.query(KnowledgeEdge).filter(
        KnowledgeEdge.task_id == task_id,
        (
            KnowledgeEdge.source_node_id.in_(matched_ids)
            | KnowledgeEdge.target_node_id.in_(matched_ids)
        ),
    )
    for edge in edge_stmt.all():
        neighbour_ids.add(edge.source_node_id)
        neighbour_ids.add(edge.target_node_id)

    all_relevant_ids = matched_ids | neighbour_ids
    relevant_nodes = [n for n in all_nodes if n.id in all_relevant_ids]
    relevant_edges = [
        e for e in edge_stmt.all()
        if e.source_node_id in all_relevant_ids
        and e.target_node_id in all_relevant_ids
    ]

    # Build compact text block
    lines = ["【知识图谱上下文（与当前对话相关的实体与关系）】"]

    node_by_id = {n.id: n for n in relevant_nodes}
    lines.append("实体：")
    for n in relevant_nodes:
        alias_str = f" (别名: {', '.join(n.aliases[:5])})" if n.aliases else ""
        lines.append(f"  - {n.name} [{n.node_type}]{alias_str}")

    if relevant_edges:
        lines.append("关系：")
        for e in relevant_edges[:20]:  # cap at 20 edges to keep context compact
            src = node_by_id.get(e.source_node_id)
            tgt = node_by_id.get(e.target_node_id)
            if src and tgt:
                lines.append(
                    f"  - {src.name} --[{e.relation}]--> {tgt.name}"
                    f" (置信度: {e.weight:.1f})"
                )

    logger.debug(
        "GraphRAG chat context: %d entity(s), %d relation(s) for task %s.",
        len(relevant_nodes), len(relevant_edges), task_id,
    )
    return "\n".join(lines)


def _build_chat_messages(
    task: Task,
    user_message: str,
    *,
    scene_id: Optional[str] = None,
    db: Session | None = None,
) -> list[dict[str, str]]:
    """Construct the LLM message list for an editor chat turn.

    The system prompt includes the current script YAML, character profiles,
    graph context from the knowledge graph (when available), and optionally
    the targeted scene data so the model has full context.
    """
    # -- Build context blocks -----------------------------------------------
    context_parts: list[str] = []

    if task.summary:
        context_parts.append(f"## Task Summary\n{task.summary}")

    # GraphRAG context: query knowledge_nodes/edges for entity mentions
    if db is not None and task.id:
        graph_ctx = _build_graph_context(db, task.id, user_message)
        if graph_ctx:
            context_parts.append(graph_ctx)

    if task.characters_json:
        context_parts.append(
            f"## Characters\n```json\n{json.dumps(task.characters_json, ensure_ascii=False, indent=2)}\n```"
        )

    if task.script_yaml:
        yaml_text = task.script_yaml
        # Cap at 60000 chars to stay well within the 128K context window
        # (the YAML is the largest context block; all other blocks combined
        #  are typically under 5K chars)
        if len(yaml_text) > 60000:
            yaml_text = yaml_text[:60000] + (
                f"\n\n... (truncated, {len(task.script_yaml) - 60000} more chars)"
            )
        context_parts.append(f"## Current Script (YAML)\n```yaml\n{yaml_text}\n```")

    # Scene-specific context
    if scene_id and task.script_json:
        scenes = task.script_json.get("scenes", [])
        target_scene = None
        for s in scenes:
            if isinstance(s, dict) and s.get("id") == scene_id:
                target_scene = s
                break
        if target_scene:
            context_parts.append(
                f"## Current Scene ({scene_id})\n```json\n{json.dumps(target_scene, ensure_ascii=False, indent=2)}\n```"
            )
        else:
            context_parts.append(
                f"## Note\nScene `{scene_id}` was requested but not found in the current script."
            )

    context_block = "\n\n".join(context_parts) if context_parts else "No script context available yet."

    system_prompt = (
        "You are an AI script editor for NovelScript. "
        "You help users write and refine structured scripts. "
        "When you suggest concrete changes, output a JSON Patch operation "
        "inside a ```json code fence:\n\n"
        '```json\n{"op": "replace", "path": "/scenes/0/title", "value": "New Title"}\n```\n\n'
        "Supported operations: replace, add, remove. "
        "The path is an RFC 6901 JSON Pointer into the script JSON document.\n\n"
        "Current task context:\n\n"
        f"{context_block}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


# ============================================================================
# Routes
# ============================================================================


@router.post("/chat/{task_id}")
def chat(
    task_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message to the AI editor for a given task.

    Returns the AI's text reply and, if the reply contains a JSON Patch
    suggestion, the parsed patch object.
    """
    tid = _parse_task_id(task_id)

    # 1. Fetch Task
    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    require_ownership(task, current_user, resource_name="任务", action="编辑")

    # 2. Build prompt & call LLM
    messages = _build_chat_messages(
        task, body.message, scene_id=body.scene_id, db=db,
    )

    try:
        llm = get_llm("ai_chat", 0.7)
        ai_msg = invoke_llm_with_retry(llm, messages, "ai_chat")
        reply_text = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)

        # Extract thinking / reasoning content when the model provides it
        thinking = None
        if hasattr(ai_msg, "additional_kwargs"):
            thinking = (
                ai_msg.additional_kwargs.get("reasoning_content")
                or ai_msg.additional_kwargs.get("thinking")
            )
        if not thinking and hasattr(ai_msg, "reasoning_content"):
            thinking = ai_msg.reasoning_content
    except Exception as exc:
        logger.exception("LLM call failed for task %s", task_id)
        raise HTTPException(
            status_code=503,
            detail=f"AI service unavailable: {exc}",
        ) from exc

    # 3. Persist dialogue rows
    user_dialogue = Dialogue(
        task_id=task.id,
        user_id=current_user.id,
        role="user",
        content=body.message,
        meta={"scene_id": body.scene_id} if body.scene_id else {},
    )
    dialogue_crud.create(db, user_dialogue)

    assistant_dialogue = Dialogue(
        task_id=task.id,
        user_id=current_user.id,
        role="assistant",
        content=reply_text,
    )
    dialogue_crud.create(db, assistant_dialogue)

    # 4. Extract JSON Patch (best-effort)
    patch_obj = _extract_json_patch(reply_text)

    # Attach extracted patch to the assistant dialogue row
    if patch_obj:
        assistant_dialogue.patch_json = patch_obj
        db.add(assistant_dialogue)
        db.flush()

    return BaseResponse(
        code=200,
        message="Chat response generated",
        data={
            "reply": reply_text,
            "patch": patch_obj,
            "thinking": thinking,
        },
    )


@router.post("/apply_patch/{task_id}")
def apply_patch(
    task_id: str,
    body: PatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a JSON Patch operation to the task's ``script_json``.

    The operation is persisted as an ``Operation`` row so it can be undone.
    Returns the updated script.
    """
    tid = _parse_task_id(task_id)

    # 1. Fetch task
    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    require_ownership(task, current_user, resource_name="任务", action="编辑")

    if task.script_json is None:
        task.script_json = {}

    # 2. Capture previous value at the target path for rollback
    prev_snapshot: Optional[dict[str, Any]] = None
    try:
        old_value = _get_at_path(task.script_json, body.path)
        prev_snapshot = {body.path: old_value}
    except (KeyError, IndexError, ValueError):
        # Path does not exist yet — this is fine for "add"
        prev_snapshot = None

    # 3. Apply the patch (mutates task.script_json in place)
    try:
        _apply_patch_op(task.script_json, body.op, body.path, body.value)
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Patch failed: {exc}",
        ) from exc

    # Persist the updated script (flag_modified required — JSONB is mutable)
    flag_modified(task, "script_json")
    db.add(task)
    db.flush()

    # 4. Record the operation
    operation = Operation(
        task_id=task.id,
        user_id=current_user.id,
        type="ai_patch",
        target_path=body.path,
        diff_json={"op": body.op, "path": body.path, "value": body.value},
        previous_snapshot=prev_snapshot,
    )
    operation_crud.create(db, operation)

    return BaseResponse(
        code=200,
        message="Patch applied",
        data={
            "script_json": task.script_json,
            "operation_id": str(operation.id),
        },
    )


@router.post("/undo/{task_id}")
def undo(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Roll back the most recent non-rollback operation for a task.

    Finds the latest ``Operation`` whose type is not ``rollback``,
    reverses it, writes a compensating ``rollback`` row, and returns
    the restored script.
    """
    tid = _parse_task_id(task_id)

    # 1. Fetch task
    task = task_crud.get(db, tid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    require_ownership(task, current_user, resource_name="任务", action="编辑")

    # 2. Find most recent non-rollback operation
    from sqlalchemy import desc, select

    stmt = (
        select(Operation)
        .where(
            Operation.task_id == task.id,
            Operation.type != "rollback",
            Operation.applied == True,
        )
        .order_by(desc(Operation.created_at))
        .limit(1)
    )
    result = db.execute(stmt)
    last_op = result.scalars().first()

    if last_op is None:
        raise HTTPException(
            status_code=400,
            detail="No operations to undo for this task",
        )

    # 3. Determine the reversing patch
    original = last_op.diff_json  # {op, path, value}
    orig_op = original.get("op", "")
    orig_path = original.get("path", "")
    prev = last_op.previous_snapshot or {}

    if task.script_json is None:
        task.script_json = {}

    reverse_op: str
    reverse_value: Any = None

    if orig_op == "replace":
        reverse_op = "replace"
        reverse_value = prev.get(orig_path)
    elif orig_op == "add":
        reverse_op = "remove"
        reverse_value = None
    elif orig_op == "remove":
        reverse_op = "add"
        reverse_value = prev.get(orig_path)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot undo operation of type {orig_op!r}",
        )

    # 4. Capture current state before reversal (for potential redo)
    try:
        current_value = _get_at_path(task.script_json, orig_path)
    except (KeyError, IndexError, ValueError):
        current_value = None
    rollback_snapshot = {orig_path: current_value} if current_value is not None else None

    # 5. Apply the reversal
    try:
        if reverse_op == "remove":
            _apply_patch_op(task.script_json, reverse_op, orig_path, None)
        else:
            _apply_patch_op(task.script_json, reverse_op, orig_path, reverse_value)
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Undo failed: {exc}",
        ) from exc

    flag_modified(task, "script_json")
    db.add(task)
    db.flush()

    # Mark the original operation as un-applied so it cannot be undone twice
    last_op.applied = False
    db.add(last_op)
    db.flush()

    # 6. Record the rollback
    rollback = Operation(
        task_id=task.id,
        user_id=current_user.id,
        type="rollback",
        target_path=orig_path,
        diff_json={
            "op": reverse_op,
            "path": orig_path,
            "value": reverse_value,
            "undone_operation_id": str(last_op.id),
        },
        previous_snapshot=rollback_snapshot,
    )
    operation_crud.create(db, rollback)

    return BaseResponse(
        code=200,
        message="Operation undone",
        data={
            "script_json": task.script_json,
            "undone_operation_id": str(last_op.id),
            "rollback_operation_id": str(rollback.id),
        },
    )
