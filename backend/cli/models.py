"""Pydantic V2 models for the NovelScript Pipeline Engine.

All data structures used throughout the pipeline — from raw novel chapters
to the final structured Script output — are defined here with strict validation.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ===========================================================================
# Chapter — raw input after splitting
# ===========================================================================


class Chapter(BaseModel):
    """A single chapter extracted from the source novel."""

    text: str = Field(..., description="Full text content of the chapter")
    title: str = Field(..., description="Chapter title (e.g. '第一章 大梦初醒')")
    index: int = Field(..., ge=0, description="Zero-based chapter index in the novel")


class ParagraphGroup(BaseModel):
    """A paragraph-aligned block of text that fits within a character budget.

    Short paragraphs (≤32 chars) are merged with neighbours to avoid
    sending one-liner speech or narration to the LLM in isolation.
    """

    text: str = Field(..., description="Grouped paragraph text")
    offset_start: int = Field(0, description="Character offset of first paragraph in the source text")
    offset_end: int = Field(0, description="Character offset after the last paragraph")


# ===========================================================================
# Element — atomic unit inside a scene (action, dialogue, heading, etc.)
# ===========================================================================


class Element(BaseModel):
    """A single script element — maps to a Fountain line type."""

    type: str = Field(
        ...,
        description="Element type: action, dialogue, heading, transition, parenthetical, "
        "character, note, or lyric",
    )
    content: str = Field(..., description="The element's text content")
    source_ref: Optional[dict] = Field(
        None,
        description="Bidirectional trace anchor: {chapter_id, offset: [start, end]}",
    )


# ===========================================================================
# Scene — a sequence of elements sharing a location / time
# ===========================================================================


class Scene(BaseModel):
    """A single scene composed of script elements."""

    scene_id: str = Field(..., description="Unique scene identifier, e.g. 's_001'")
    heading: str = Field(..., description="Scene heading (slug line)")
    location: str = Field(..., description="Parsed location from heading")
    time_of_day: str = Field(..., description="Parsed time-of-day from heading")
    elements: list[Element] = Field(default_factory=list, description="Ordered elements in the scene")
    characters_present: list[str] = Field(
        default_factory=list, description="Character IDs present in this scene"
    )


# ===========================================================================
# Character — entity extracted from the novel
# ===========================================================================


class Character(BaseModel):
    """A character entity with aliases and extensible properties."""

    id: str = Field(..., description="Unique character ID, e.g. 'char_01'")
    name: str = Field(..., description="Primary display name")
    aliases: list[str] = Field(default_factory=list, description="Alternate names / nicknames")
    properties: dict = Field(
        default_factory=dict,
        description="Extensible traits dict: age, gender, role, description, etc.",
    )


# ===========================================================================
# Knowledge Graph
# ===========================================================================


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph — character, location, item, or event."""

    id: str = Field(..., description="Unique node ID")
    name: str = Field(..., description="Human-readable node name")
    node_type: str = Field(
        ...,
        description="Node category: character, location, item, event, organization",
    )
    properties: dict = Field(default_factory=dict, description="Extensible key-value metadata")


class KnowledgeEdge(BaseModel):
    """A directed edge between two knowledge graph nodes."""

    source_node_id: str = Field(..., description="Source node ID")
    target_node_id: str = Field(..., description="Target node ID")
    relation: str = Field(..., description="Relationship label, e.g. 'friend_of', 'located_in'")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Edge confidence weight 0–1")


class KnowledgeGraph(BaseModel):
    """The extracted knowledge graph for the entire novel."""

    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


# ===========================================================================
# Script — the final output
# ===========================================================================


class Script(BaseModel):
    """Complete structured script output — the pipeline's final product."""

    meta: dict = Field(
        default_factory=dict,
        description="Metadata: title, author, source_word_count, pipeline_version, etc.",
    )
    summary: str = Field("", description="One-paragraph summary of the adapted script")
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    knowledge_graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
