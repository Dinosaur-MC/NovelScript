"""Exporter — serializes the Script model to YAML (primary) and JSON.

YAML output uses PyYAML with ``allow_unicode=True`` for CJK text.
JSON output uses Pydantic's ``model_dump_json``.
"""

from __future__ import annotations

import json
import logging

import yaml

from cli.models import Script

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


def _script_to_dict(script: Script) -> dict:
    """Convert a Script model to a plain dict for YAML serialization."""
    return {
        "meta": script.meta,
        "summary": script.summary,
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "aliases": c.aliases,
                "properties": c.properties,
            }
            for c in script.characters
        ],
        "scenes": [
            {
                "scene_id": s.scene_id,
                "heading": s.heading,
                "location": s.location,
                "time_of_day": s.time_of_day,
                "characters_present": s.characters_present,
                "elements": [
                    {
                        "type": e.type,
                        "content": e.content,
                        "source_ref": e.source_ref,
                    }
                    for e in s.elements
                ],
            }
            for s in script.scenes
        ],
        "knowledge_graph": {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "node_type": n.node_type,
                    "properties": n.properties,
                }
                for n in script.knowledge_graph.nodes
            ],
            "edges": [
                {
                    "source_node_id": e.source_node_id,
                    "target_node_id": e.target_node_id,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in script.knowledge_graph.edges
            ],
        },
    }
