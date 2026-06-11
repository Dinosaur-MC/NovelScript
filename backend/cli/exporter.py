"""Exporter — serializes the Script model to YAML (primary) and JSON.

YAML output uses PyYAML with ``allow_unicode=True`` for CJK text.
JSON output uses Pydantic's ``model_dump_json``.
"""

from __future__ import annotations

import json
import logging

import yaml

from cli.models import (
    ActionElement,
    BoneyardElement,
    DialogueBlock,
    LyricElement,
    Script,
    ScriptElement,
    SectionElement,
    SourceRef,
    SynopsisElement,
    TransitionElement,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------


def to_yaml(script: Script) -> str:
    """Serialize a Script to a YAML string.

    Uses PyYAML's ``safe_dump`` for compatibility, with ``allow_unicode``
    enabled so CJK characters are written as-is rather than escaped.

    Args:
        script: The Script model to export.

    Returns:
        A YAML-formatted string.
    """
    data = _script_to_dict(script)
    output = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    logger.info("Exported YAML (%d chars).", len(output))
    return output


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(script: Script) -> str:
    """Serialize a Script to a pretty-printed JSON string.

    Args:
        script: The Script model to export.

    Returns:
        A JSON-formatted string with 2-space indentation.
    """
    output = script.model_dump_json(indent=2)
    logger.info("Exported JSON (%d chars).", len(output))
    return output


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_source_ref(ref: SourceRef | None) -> dict | None:
    """Convert a SourceRef model to a plain dict for serialization.

    Returns ``None`` when *ref* is ``None``.  Omits ``document_id`` when it
    is an empty string (CLI-only runs don't set it).
    """
    if ref is None:
        return None
    result: dict = {
        "chapter_id": ref.chapter_id,
        "offset": ref.offset,
        "confidence": ref.confidence,
    }
    if ref.document_id:
        result["document_id"] = ref.document_id
    return result


def _serialize_element(elem: ScriptElement) -> dict:
    """Convert a ScriptElement to a plain dict for serialization."""
    if isinstance(elem, ActionElement):
        return {
            "type": "action",
            "text": elem.text,
            "is_forced": elem.is_forced,
            "is_centered": elem.is_centered,
            "source_ref": _serialize_source_ref(elem.source_ref),
        }
    elif isinstance(elem, DialogueBlock):
        return {
            "type": "dialogue_block",
            "character_id": elem.character_id,
            "character_name": elem.character_name,
            "is_character_forced": elem.is_character_forced,
            "character_extension": elem.character_extension,
            "parenthetical": elem.parenthetical,
            "dialogue": elem.dialogue,
            "is_dual": elem.is_dual,
            "source_ref": _serialize_source_ref(elem.source_ref),
        }
    elif isinstance(elem, TransitionElement):
        return {
            "type": "transition",
            "text": elem.text,
            "transition_type": elem.transition_type.value if elem.transition_type else None,
            "is_forced": elem.is_forced,
            "source_ref": _serialize_source_ref(elem.source_ref),
        }
    elif isinstance(elem, LyricElement):
        return {
            "type": "lyric",
            "text": elem.text,
            "source_ref": _serialize_source_ref(elem.source_ref),
        }
    elif isinstance(elem, BoneyardElement):
        return {"type": "boneyard", "text": elem.text}
    elif isinstance(elem, SectionElement):
        return {"type": "section", "text": elem.text, "level": elem.level}
    elif isinstance(elem, SynopsisElement):
        return {"type": "synopsis", "text": elem.text}
    else:
        # PageBreakElement and fallbacks
        return {"type": getattr(elem, "type", "unknown")}


def _script_to_dict(script: Script) -> dict:
    """Convert a Script model to a plain dict for YAML serialization.

    Output follows the Schema 2.1.0 structure: title_page, system_meta,
    meta, summary, characters, scenes, knowledge_graph.
    """
    return {
        "title_page": script.title_page.model_dump(by_alias=True, exclude_none=True),
        "system_meta": script.system_meta.model_dump(exclude_none=True),
        "meta": script.meta,
        "summary": script.summary,
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "aliases": c.aliases,
                "description": c.description,
                "metadata": c.metadata,
            }
            for c in script.characters
        ],
        "scenes": [
            {
                "scene_id": s.scene_id,
                "heading": {
                    "text": s.heading.text,
                    "int_ext": s.heading.int_ext.value if s.heading.int_ext else None,
                    "location": s.heading.location,
                    "time_of_day": s.heading.time_of_day.value,
                    "is_forced": s.heading.is_forced,
                    "narrative_mode": s.heading.narrative_mode.value if s.heading.narrative_mode else None,
                },
                "characters_present": s.characters_present,
                "elements": [_serialize_element(e) for e in s.elements],
                "source_ref": _serialize_source_ref(s.source_ref),
                "metadata": s.metadata,
            }
            for s in script.scenes
        ],
        "knowledge_graph": {
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.type,
                    "metadata": n.metadata,
                }
                for n in script.knowledge_graph.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in script.knowledge_graph.edges
            ],
        },
    }
