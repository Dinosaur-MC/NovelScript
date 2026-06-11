"""AI editor / chat API — script-centric AI-assisted editing.

Routes
------
POST /chat/{script_id}        — Send a chat message; optionally get a JSON Patch back.
POST /apply_patch/{script_id} — Apply a JSON Patch to the script's script_json.
POST /undo/{script_id}        — Roll back the most recent patch operation.

Uses LangGraph for structured tool-call based patch generation (S5).
GraphRAG context enriches AI prompts with entity/relation data from KG.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import desc, select as sa_select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from cli.llm_router import get_llm, invoke_llm_with_retry

from app.core.auth_middleware import get_current_user, require_ownership
from app.core.db import get_db
from app.models.http import BaseResponse
from app.models.sql import Dialogue, KnowledgeEdge, KnowledgeNode, Operation, Script, Task, User
from app.services.base import BaseCRUD
from app.services.graphrag_service import build_graph_context, generate_patch_with_langgraph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/editor", tags=["Editor"])

# ── CRUD instances ──────────────────────────────────────────────────
script_crud = BaseCRUD[Script](Script)
task_crud = BaseCRUD[Task](Task)
dialogue_crud = BaseCRUD[Dialogue](Dialogue)
operation_crud = BaseCRUD[Operation](Operation)


# ── Request models ──────────────────────────────────────────────────

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


# ── JSON Pointer helpers (RFC 6901) ─────────────────────────────────

def _parse_json_pointer(path: str) -> list[str]:
    """Parse an RFC 6901 JSON Pointer into path segments."""
    if not path.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'")
    return [segment.replace("~1", "/").replace("~0", "~") for segment in path[1:].split("/")]


def _get_at_path(doc: dict, path: str) -> Any:
    """Get the value at *path* in *doc* (JSON Pointer)."""
    segments = _parse_json_pointer(path)
    current: Any = doc
    for i, seg in enumerate(segments):
        if seg == "":
            raise ValueError(f"Empty reference token at position {i}")
        if isinstance(current, dict):
            if seg not in current:
                raise KeyError(f"Key {seg!r} not found at /{'/'.join(segments[:i])}")
            current = current[seg]
        elif isinstance(current, list):
            try:
                idx = int(seg)
            except ValueError:
                raise ValueError(f"List index must be integer, got {seg!r}")
            if idx < 0 or idx >= len(current):
                raise IndexError(f"Index {idx} out of range for list of length {len(current)}")
            current = current[idx]
        else:
            raise ValueError(f"Cannot index into {type(current).__name__} at /{'/'.join(segments[:i])}")
    return current


def _set_at_path(doc: dict, path: str, value: Any) -> None:
    """Set the value at *path* in *doc* (JSON Pointer), creating intermediate keys."""
    segments = _parse_json_pointer(path)
    current: Any = doc
    for i in range(len(segments) - 1):
        seg = segments[i]
        if isinstance(current, list):
            try:
                idx = int(seg)
            except ValueError:
                raise ValueError(f"List index must be integer, got {seg!r}")
            if idx == len(current):
                current.append({})
            current = current[idx]
        elif isinstance(current, dict):
            if seg not in current:
                current[seg] = {}
            current = current[seg]
        else:
            raise ValueError(f"Cannot descend into {type(current).__name__}")
    last = segments[-1]
    if isinstance(current, list):
        try:
            idx = int(last)
        except ValueError:
            raise ValueError(f"List index must be integer, got {last!r}")
        if idx == len(current):
            current.append(value)
        else:
            current[idx] = value
    elif isinstance(current, dict):
        current[last] = value


def _remove_at_path(doc: dict, path: str) -> None:
    """Remove the key/index at *path* from *doc*."""
    segments = _parse_json_pointer(path)
    current: Any = doc
    for i in range(len(segments) - 1):
        seg = segments[i]
        if isinstance(current, dict):
            current = current[seg]
        elif isinstance(current, list):
            current = current[int(seg)]
    last = segments[-1]
    if isinstance(current, dict):
        del current[last]
    elif isinstance(current, list):
        del current[int(last)]


def _apply_patch_op(doc: dict, op: str, path: str, value: Any) -> None:
    """Apply a single RFC 6902 JSON Patch operation to *doc* in place."""
    if op == "add":
        _set_at_path(doc, path, value)
    elif op == "remove":
        _remove_at_path(doc, path)
    elif op == "replace":
        _set_at_path(doc, path, value)
    else:
        raise ValueError(f"Unsupported patch operation: {op!r}")


# ── UUID helper ─────────────────────────────────────────────────────

def _parse_script_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid script_id: {raw!r}")


# ── Chat message builder (with GraphRAG context) ────────────────────

def _build_chat_messages(
    db: Session,
    script: Script,
    user_message: str,
    *,
    scene_id: Optional[str] = None,
) -> list[dict[str, str]]:
    """Construct the LLM message list for an editor chat turn.

    Includes GraphRAG context from the knowledge graph (S5).
    """
    context_parts: list[str] = []

    if script.summary:
        context_parts.append(f"## Task Summary\n{script.summary}")

    if script.characters_json:
        context_parts.append(
            f"## Characters\n```json\n{json.dumps(script.characters_json, ensure_ascii=False, indent=2)}\n```"
        )

    # ── GraphRAG context (S5) ────────────────────────────────────────
    novel_id = str(script.novel_id) if script.novel_id else None
    script_id = str(script.id) if script.id else ""
    kg_context = build_graph_context(
        db, novel_id=novel_id, script_id=script_id, query=user_message,
    )
    if kg_context:
        context_parts.append(kg_context)

    if script.script_yaml:
        yaml_text = script.script_yaml
        if len(yaml_text) > 60000:
            yaml_text = yaml_text[:60000] + (
                f"\n\n... (truncated, {len(script.script_yaml) - 60000} more chars)"
            )
        context_parts.append(f"## Current Script (YAML)\n```yaml\n{yaml_text}\n```")

    if scene_id and script.script_json:
        scenes = script.script_json.get("scenes", [])
        target_scene = next(
            (s for s in scenes if isinstance(s, dict) and s.get("id") == scene_id),
            None,
        )
        if target_scene:
            context_parts.append(
                f"## Current Scene ({scene_id})\n```json\n{json.dumps(target_scene, ensure_ascii=False, indent=2)}\n```"
            )
        else:
            context_parts.append(f"## Note\nScene `{scene_id}` was requested but not found in the script. Available scenes: {len(scenes)} total.")

    context_block = "\n\n".join(context_parts) if context_parts else "No script context available yet."

    system_prompt = (
        "You are an AI script editor for NovelScript. "
        "You help users write and refine structured scripts. "
        "When you suggest concrete changes, use the 'apply_script_patch' tool "
        "to generate a structured JSON Patch operation.\n\n"
        "Supported patch operations:\n"
        "- replace: Update an existing value at the given path.\n"
        "- add: Insert a new value at the given path.\n"
        "- remove: Delete the value at the given path.\n\n"
        "Path is an RFC 6901 JSON Pointer into the script JSON document. Examples:\n"
        '- "/scenes/0/title" — change a scene title\n'
        '- "/scenes/0/elements/0/dialogue" — change dialogue text\n'
        '- "/characters/0/name" — rename a character\n\n'
        "Use the tool to output your patch. If no change is needed, "
        "just respond conversationally without calling the tool.\n\n"
        "Current task context:\n\n"
        f"{context_block}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


# ══════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════


@router.post("/chat/{script_id}")
def chat(
    script_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message to the AI editor for a given script.

    Uses LangGraph workflow with tool calling for structured patch generation (S5).
    GraphRAG context enriches the prompt with relevant KG entities (S5).
    Falls back to legacy code-fence extraction if LangGraph is unavailable.
    """
    sid = _parse_script_id(script_id)

    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail=f"Script {script_id!r} not found")
    require_ownership(script, current_user, resource_name="剧本", action="编辑")

    # Build messages with GraphRAG context
    messages = _build_chat_messages(db, script, body.message, scene_id=body.scene_id)

    # Try LangGraph tool-call approach first
    patch_obj = None
    reply_text = ""
    langgraph_succeeded = False

    try:
        system_msg = messages[0]["content"]
        user_msg = messages[1]["content"]
        reply_text, patch_obj = generate_patch_with_langgraph(system_msg, user_msg)
        if reply_text:
            langgraph_succeeded = True
            logger.info("LangGraph patch generation succeeded for script %s", script_id)
    except Exception as exc:
        logger.warning("LangGraph patch generation failed for script %s: %s", script_id, exc)
        langgraph_succeeded = False

    # Fallback: legacy LLM call + regex extraction
    if not langgraph_succeeded or not reply_text:
        logger.info("Falling back to legacy LLM call for script %s", script_id)
        try:
            llm = get_llm("ai_chat", 0.7)
            ai_msg = invoke_llm_with_retry(llm, messages, "ai_chat")
            reply_text = ai_msg.content if hasattr(ai_msg, "content") else str(ai_msg)
        except Exception as exc:
            logger.exception("LLM call failed for script %s", script_id)
            raise HTTPException(status_code=503, detail=f"AI service unavailable: {exc}") from exc

        # Legacy regex-based patch extraction (fallback)
        if not patch_obj:
            patch_obj = _extract_json_patch(reply_text)

    # Extract thinking/reasoning if present (only in legacy path)
    thinking = None
    if not langgraph_succeeded:
        thinking = _extract_thinking(ai_msg)

    # Find any associated task for backward compat
    assoc_task = db.execute(
        sa_select(Task).where(Task.script_id == sid).limit(1)
    ).scalar()

    # Persist dialogue
    user_dialogue = Dialogue(
        script_id=sid,
        task_id=assoc_task.id if assoc_task else None,
        user_id=current_user.id,
        role="user",
        content=body.message,
        meta={"scene_id": body.scene_id} if body.scene_id else {},
    )
    dialogue_crud.create(db, user_dialogue)

    assistant_dialogue = Dialogue(
        script_id=sid,
        task_id=assoc_task.id if assoc_task else None,
        user_id=current_user.id,
        role="assistant",
        content=reply_text,
    )
    dialogue_crud.create(db, assistant_dialogue)

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


@router.post("/apply_patch/{script_id}")
def apply_patch(
    script_id: str,
    body: PatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a JSON Patch operation to the script's ``script_json``."""
    sid = _parse_script_id(script_id)

    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail=f"Script {script_id!r} not found")
    require_ownership(script, current_user, resource_name="剧本", action="编辑")

    if script.script_json is None:
        script.script_json = {}

    prev_snapshot: Optional[dict[str, Any]] = None
    try:
        old_value = _get_at_path(script.script_json, body.path)
        prev_snapshot = {body.path: old_value}
    except (KeyError, IndexError, ValueError):
        prev_snapshot = None

    try:
        _apply_patch_op(script.script_json, body.op, body.path, body.value)
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Patch failed: {exc}") from exc

    flag_modified(script, "script_json")
    db.add(script)
    db.flush()

    assoc_task = db.execute(
        sa_select(Task).where(Task.script_id == sid).limit(1)
    ).scalar()

    operation = Operation(
        script_id=sid,
        task_id=assoc_task.id if assoc_task else None,
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
            "script_json": script.script_json,
            "operation_id": str(operation.id),
        },
    )


@router.post("/undo/{script_id}")
def undo(
    script_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Roll back the most recent non-rollback operation for a script."""
    sid = _parse_script_id(script_id)

    script = script_crud.get(db, sid)
    if script is None:
        raise HTTPException(status_code=404, detail=f"Script {script_id!r} not found")
    require_ownership(script, current_user, resource_name="剧本", action="编辑")

    stmt = (
        sa_select(Operation)
        .where(
            Operation.script_id == sid,
            Operation.type != "rollback",
            Operation.applied == True,
        )
        .order_by(desc(Operation.created_at))
        .limit(1)
    )
    last_op = db.execute(stmt).scalars().first()

    if last_op is None:
        raise HTTPException(status_code=400, detail="No operations to undo for this script")

    original = last_op.diff_json
    orig_op = original.get("op", "")
    orig_path = original.get("path", "")
    prev = last_op.previous_snapshot or {}

    if script.script_json is None:
        script.script_json = {}

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
        raise HTTPException(status_code=400, detail=f"Cannot undo operation of type {orig_op!r}")

    try:
        current_value = _get_at_path(script.script_json, orig_path)
    except (KeyError, IndexError, ValueError):
        current_value = None
    rollback_snapshot = {orig_path: current_value} if current_value is not None else None

    try:
        if reverse_op == "remove":
            _apply_patch_op(script.script_json, reverse_op, orig_path, None)
        else:
            _apply_patch_op(script.script_json, reverse_op, orig_path, reverse_value)
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Undo failed: {exc}") from exc

    flag_modified(script, "script_json")
    db.add(script)
    db.flush()

    last_op.applied = False
    db.add(last_op)
    db.flush()

    assoc_task = db.execute(
        sa_select(Task).where(Task.script_id == sid).limit(1)
    ).scalar()

    rollback = Operation(
        script_id=sid,
        task_id=assoc_task.id if assoc_task else None,
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
            "script_json": script.script_json,
            "undone_operation_id": str(last_op.id),
            "rollback_operation_id": str(rollback.id),
        },
    )


# ── Legacy helpers (kept for fallback) ─────────────────────────────

_PATCH_PATTERN = re.compile(
    r'```(?:json)?\s*\n?\s*(\{.*?"op"\s*:\s*"(?:replace|add|remove)".*?\})\s*\n?\s*```',
    re.DOTALL,
)


def _extract_json_patch(text: str) -> Optional[dict]:
    """Try to extract a JSON Patch object from an AI reply.

    Legacy fallback in case LangGraph tool-call is unavailable.
    """
    for match in _PATCH_PATTERN.finditer(text):
        try:
            obj = json.loads(match.group(1))
            if "op" in obj and "path" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _extract_thinking(ai_msg) -> Optional[str]:
    """Extract reasoning/thinking from an LLM response."""
    if ai_msg is None:
        return None
    if hasattr(ai_msg, "additional_kwargs"):
        thinking = (
            ai_msg.additional_kwargs.get("reasoning_content")
            or ai_msg.additional_kwargs.get("thinking")
        )
        if thinking:
            return thinking
    if hasattr(ai_msg, "reasoning_content"):
        return ai_msg.reasoning_content
    return None
