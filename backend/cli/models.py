"""Pydantic V2 models for the NovelScript Pipeline Engine.

All data structures used throughout the pipeline — from raw novel chapters
to the final structured Script output — are defined here with strict validation.

Schema version: 2.1.0  (aligned with docs/YAML_Schema_设计说明.md)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


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
# SourceRef — bidirectional trace anchor
# ===========================================================================


class SourceRef(BaseModel):
    """Bidirectional trace anchor — maps a script element back to source text.

    Used for the frontend's source-linking feature: clicking an element in
    the script editor highlights the corresponding passage in the novel reader.
    """

    document_id: str = Field(
        "",
        description="Global trace root ID (set by DB layer; empty in CLI-only runs)",
    )
    chapter_id: str = Field(..., min_length=1, description="Chapter identifier, e.g. 'ch_00'")
    offset: list[int] = Field(
        ..., min_length=2, max_length=2,
        description="Character offset range [start, end) — Python slice style",
    )
    confidence: Literal["exact", "prefix", "estimated", "inferred"] = Field(
        "estimated",
        description=(
            "Match confidence: 'exact' = full-text match, 'prefix' = first-10-chars match, "
            "'estimated' = ratio-based position fallback, 'inferred' = LLM-generated content"
        ),
    )


# ===========================================================================
# Enums — heading sub-fields
# ===========================================================================


class TimeOfDay(str, Enum):
    """Standard time-of-day for scene headings (Fountain 1.1 + 短剧扩展)."""

    DAY = "DAY"
    NIGHT = "NIGHT"
    DAWN = "DAWN"
    DUSK = "DUSK"
    LATER = "LATER"
    CONTINUOUS = "CONTINUOUS"
    SAME = "SAME"
    UNKNOWN = "UNKNOWN"


class IntExt(str, Enum):
    """Interior / exterior indicator for scene headings."""

    INT = "INT."
    EXT = "EXT."
    INT_EXT = "INT./EXT."
    EST = "EST."


class NarrativeMode(str, Enum):
    """Narrative mode marker for non-linear scenes."""

    FLASHBACK = "FLASHBACK"
    FLASHFORWARD = "FLASHFORWARD"
    DREAM = "DREAM"
    VISION = "VISION"
    MONTAGE = "MONTAGE"


class TransitionType(str, Enum):
    """Transition sub-types."""

    CUT = "cut"
    FADE_IN = "fade_in"
    FADE_OUT = "fade_out"
    DISSOLVE = "dissolve"
    SMASH_CUT = "smash_cut"
    INTERCUT = "intercut"


# ===========================================================================
# Heading — structured slug-line
# ===========================================================================


class Heading(BaseModel):
    """Structured scene heading (Fountain slug line).

    Schema §5.5.2 — each heading carries the original text as a fallback
    plus parsed sub-fields for structured access.
    """

    text: str = Field(..., description="Original full heading text (fallback for export)")
    int_ext: Optional[IntExt] = Field(None, description="INT | EXT | INT./EXT. | EST")
    location: str = Field(..., description="Location name extracted from heading")
    time_of_day: TimeOfDay = Field(TimeOfDay.UNKNOWN, description="Standard time-of-day")
    is_forced: bool = Field(False, description="Whether heading was forced with '.' prefix")
    narrative_mode: Optional[NarrativeMode] = Field(
        None, description="Non-linear marker: FLASHBACK, DREAM, etc."
    )


# ===========================================================================
# TitlePage & SystemMeta
# ===========================================================================


class TitlePage(BaseModel):
    """Fountain-standard title page (Schema §5.1)."""

    title: str = Field("", alias="Title", description="Script title")
    credit: str = Field("改编", alias="Credit", description="Credit type")
    author: str = Field("NovelScript AI", alias="Author", description="Author / adapter")
    source: str = Field("", alias="Source", description="Original source")
    draft_date: str = Field("", alias="Draft date", description="Draft date")
    contact: Optional[str] = Field(None, alias="Contact", description="Contact info")
    notes: Optional[str] = Field(None, alias="Notes", description="Notes")

    model_config = {"populate_by_name": True}


class SystemMeta(BaseModel):
    """System-level metadata (Schema §5.2)."""

    document_id: str = Field("", description="Global trace root ID")
    model: str = Field("", description="LLM model identifier")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="Generation timestamp (ISO 8601 UTC)",
    )
    schema_version: str = Field("2.1.0", description="Schema SemVer")
    language: str = Field("zh-CN", description="IETF BCP 47 language tag")
    source_word_count: int = Field(0, description="Original text character count")
    warnings: list[str] = Field(default_factory=list, description="Runtime warnings")


# ===========================================================================
# Element types — 8 Fountain-compatible element kinds (Schema §5.6)
# ===========================================================================


class ActionElement(BaseModel):
    """Action description / scene narration (Schema §5.6.2)."""

    type: Literal["action"] = "action"
    text: str = Field(..., description="Action text")
    is_forced: bool = Field(False, description="Fountain '!' forced-action marker")
    is_centered: bool = Field(False, description="Fountain '> text <' centered text")
    source_ref: Optional[SourceRef] = Field(None, description="Trace anchor")


class DialogueBlock(BaseModel):
    """Dialogue logical block — character + parenthetical + dialogue (Schema §5.6.3)."""

    type: Literal["dialogue_block"] = "dialogue_block"
    character_id: str = Field("", description="Character ID reference")
    character_name: str = Field(..., description="Display name (maps to Fountain uppercase line)")
    is_character_forced: bool = Field(False, description="Fountain '@' forced-character marker")
    character_extension: Optional[str] = Field(
        None, description="Extension: (CONT'D), (V.O.), (O.S.), etc."
    )
    parenthetical: Optional[str] = Field(None, description="Performance direction, e.g. '(冷笑)'")
    dialogue: str = Field("", description="Dialogue text")
    is_dual: bool = Field(False, description="Fountain dual-dialogue ' ^' marker")
    source_ref: Optional[SourceRef] = Field(None, description="Trace anchor")

    @model_validator(mode="after")
    def _check_wrapping(self) -> "DialogueBlock":
        if self.parenthetical and not (
            self.parenthetical.startswith("(") and self.parenthetical.endswith(")")
        ):
            raise ValueError(
                f"parenthetical must be wrapped in (): {self.parenthetical}"
            )
        if self.character_extension and not (
            self.character_extension.startswith("(")
            and self.character_extension.endswith(")")
        ):
            raise ValueError(
                f"character_extension must be wrapped in (): {self.character_extension}"
            )
        return self


class TransitionElement(BaseModel):
    """Transition indicator (Schema §5.6.4)."""

    type: Literal["transition"] = "transition"
    text: str = Field(..., description="Transition text, e.g. 'CUT TO:'")
    transition_type: Optional[TransitionType] = Field(None, description="Transition sub-type")
    is_forced: bool = Field(False, description="Fountain '>' forced-transition marker")
    source_ref: Optional[SourceRef] = Field(None, description="Trace anchor")


class LyricElement(BaseModel):
    """Lyric / poem line (Schema §5.6.5)."""

    type: Literal["lyric"] = "lyric"
    text: str = Field(..., description="Lyric text")
    source_ref: Optional[SourceRef] = Field(None, description="Trace anchor")


class BoneyardElement(BaseModel):
    """Director / writer note — Fountain native boneyard (Schema §5.6.6)."""

    type: Literal["boneyard"] = "boneyard"
    text: str = Field(..., description="Boneyard comment text")


class SectionElement(BaseModel):
    """Section / act marker (Schema §5.6.7)."""

    type: Literal["section"] = "section"
    text: str = Field(..., description="Section title")
    level: int = Field(1, ge=1, le=4, description="Heading level (1–4, maps to #–####)")


class SynopsisElement(BaseModel):
    """Synopsis line (Schema §5.6.8)."""

    type: Literal["synopsis"] = "synopsis"
    text: str = Field(..., description="Synopsis text")


class PageBreakElement(BaseModel):
    """Forced page break (Schema §5.6.9)."""

    type: Literal["page_break"] = "page_break"


# Discriminated union — all 8 element types
ScriptElement = Union[
    ActionElement,
    DialogueBlock,
    TransitionElement,
    LyricElement,
    BoneyardElement,
    SectionElement,
    SynopsisElement,
    PageBreakElement,
]


def _normalize_flat_element(item: dict) -> dict:
    """Convert a flat LLM-format element dict to the correct typed-element dict.

    The LLM may output old-format ``{type: "dialogue", content: "..."}``
    which doesn't match any ``ScriptElement`` subtype.  This function maps
    the flat shape to the canonical one (ActionElement, DialogueBlock, etc.).
    """
    elem_type = item.get("type", "action")
    content = item.get("content", "")
    source_ref = item.get("source_ref")

    if elem_type in ("action",):
        return {"type": "action", "text": item.get("text") or content,
                "is_forced": item.get("is_forced", False),
                "is_centered": item.get("is_centered", False), "source_ref": source_ref}

    if elem_type in ("dialogue", "dialogue_block"):
        return {"type": "dialogue_block",
                "character_id": item.get("character_id", ""),
                "character_name": item.get("character_name", ""),
                "dialogue": item.get("dialogue") or content,
                "parenthetical": item.get("parenthetical"),
                "character_extension": item.get("character_extension"),
                "is_dual": item.get("is_dual", False),
                "is_character_forced": item.get("is_character_forced", False),
                "source_ref": source_ref}

    if elem_type == "transition":
        return {"type": "transition", "text": item.get("text") or content, "source_ref": source_ref}

    if elem_type == "lyric":
        return {"type": "lyric", "text": item.get("text") or content, "source_ref": source_ref}

    if elem_type == "boneyard" or elem_type == "note":
        return {"type": "boneyard", "text": item.get("text") or content}

    if elem_type == "section":
        return {"type": "section", "text": item.get("text") or content, "level": item.get("level", 1)}

    if elem_type == "synopsis":
        return {"type": "synopsis", "text": item.get("text") or content}

    if elem_type == "page_break":
        return {"type": "page_break"}

    if elem_type == "heading":
        return {"type": "action", "text": content, "source_ref": source_ref}

    if elem_type in ("character", "parenthetical"):
        # Collapse standalone character/parenthetical into dialogue_block
        return {"type": "dialogue_block",
                "character_name": content if elem_type == "character" else "",
                "dialogue": "",
                "parenthetical": content if elem_type == "parenthetical" else None,
                "source_ref": source_ref}

    # Unknown type → action fallback
    return {"type": "action", "text": item.get("text") or content, "source_ref": source_ref}


# ===========================================================================
# Scene
# ===========================================================================


class Scene(BaseModel):
    """A single scene composed of structured heading + script elements.

    Schema §5.5.1 — heading is a structured object; location and time_of_day
    are sub-fields of heading, not flat scene-level fields.

    Accepts a plain ``str`` heading from LLM output and auto-wraps it into
    a ``Heading`` object (the normalizer converts it fully in post-processing).
    """

    scene_id: str = Field(..., description="Unique scene identifier, e.g. 's_0001'")
    heading: Heading = Field(..., description="Structured heading (slug line)")
    characters_present: list[str] = Field(
        default_factory=list, description="Character IDs present in this scene"
    )
    elements: list[ScriptElement] = Field(
        default_factory=list, description="Ordered elements in the scene"
    )
    source_ref: Optional[SourceRef] = Field(
        None, description="Scene-level trace anchor (covers entire scene)"
    )
    metadata: dict = Field(default_factory=dict, description="Scene-level extension data")

    @field_validator("elements", mode="before")
    @classmethod
    def _coerce_elements(cls, v: object) -> object:
        """Auto-convert flat dicts and legacy Element instances to ScriptElement types.

        The LLM may return old-format flat dicts like ``{type: "dialogue", content: "..."}``
        that don't match any ScriptElement subtype.  This validator detects them and
        rewrites to the correct shape (e.g. ``DialogueBlock`` via ``{type: "dialogue_block",
        dialogue: "..."}``).
        """
        if not isinstance(v, list):
            return v
        result: list[object] = []
        for item in v:
            if isinstance(item, dict):
                result.append(_normalize_flat_element(item))
            elif hasattr(item, "to_script_element"):
                result.append(item.to_script_element())
            else:
                result.append(item)
        return result

    @field_validator("heading", mode="before")
    @classmethod
    def _coerce_heading(cls, v: object) -> object:
        """Accept a plain string heading from LLM output as a fallback."""
        if isinstance(v, str):
            return Heading(text=v, location=v)
        return v


# ===========================================================================
# Character
# ===========================================================================


class Character(BaseModel):
    """A character entity with aliases and extensible metadata.

    Schema §5.4 — requires description.  Properties go into ``metadata``.
    """

    id: str = Field(..., description="Unique character ID, e.g. 'char_01'")
    name: str = Field(..., description="Primary display name")
    aliases: list[str] = Field(default_factory=list, description="Alternate names / nicknames")
    description: str = Field("", description="1–3 sentence character description")
    metadata: dict = Field(
        default_factory=dict,
        description="Extension fields: age, gender, role, traits, etc.",
    )


# ===========================================================================
# Knowledge Graph
# ===========================================================================


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph — character, location, item, event, organization.

    Schema uses ``label`` for display name, ``type`` for node category,
    and ``metadata`` for extensible key-value data.
    """

    id: str = Field(..., description="Unique node ID, e.g. 'char_01', 'loc_01'")
    label: str = Field(..., alias="name", description="Human-readable node name")
    type: str = Field(
        ...,
        alias="node_type",
        description="Node category: character, location, item, event, organization",
    )
    metadata: dict = Field(
        default_factory=dict,
        alias="properties",
        description="Extensible key-value metadata (aliases, traits, description, etc.)",
    )

    model_config = {"populate_by_name": True}


class KnowledgeEdge(BaseModel):
    """A directed edge between two knowledge graph nodes.

    Schema uses ``source`` / ``target`` for endpoint node IDs.
    """

    source: str = Field(..., alias="source_node_id", description="Source node ID")
    target: str = Field(..., alias="target_node_id", description="Target node ID")
    relation: str = Field(..., description="Relationship label, e.g. 'friend_of', 'located_in'")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Edge confidence weight 0–1")

    model_config = {"populate_by_name": True}


class KnowledgeGraph(BaseModel):
    """The extracted knowledge graph for the entire novel."""

    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


# ===========================================================================
# Script — the final output
# ===========================================================================


class Script(BaseModel):
    """Complete structured script output — the pipeline's final product.

    Schema §4 — top-level structure: title_page, system_meta, meta, summary,
    characters, scenes, knowledge_graph.
    """

    title_page: TitlePage = Field(default_factory=TitlePage)
    system_meta: SystemMeta = Field(default_factory=SystemMeta)
    meta: dict = Field(
        default_factory=dict,
        description="Pipeline diagnostics: chapter_summaries, usage, warnings, etc.",
    )
    summary: str = Field("", description="One-paragraph summary of the adapted script")
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    knowledge_graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


# ===========================================================================
# Backward-compat — old flat Element for tests and legacy code
# ===========================================================================


class Element(BaseModel):
    """Legacy backward-compat element — maps to the new typed elements.

    Accepts the old ``{type, content, source_ref}`` shape and auto-converts
    to the appropriate Schema 2.1.0 element type via ``model_validate``.
    """

    type: str = Field(..., description="Element type")
    content: str = Field("", description="Element text")
    source_ref: Optional[SourceRef] = Field(None, description="Trace anchor")

    def to_script_element(self) -> "ScriptElement":
        """Convert this legacy element to the appropriate typed element."""
        if self.type == "action":
            return ActionElement(text=self.content, source_ref=self.source_ref)
        elif self.type in ("dialogue", "dialogue_block"):
            return DialogueBlock(
                character_name="", dialogue=self.content, source_ref=self.source_ref
            )
        elif self.type == "transition":
            return TransitionElement(text=self.content, source_ref=self.source_ref)
        elif self.type == "lyric":
            return LyricElement(text=self.content, source_ref=self.source_ref)
        elif self.type == "section":
            return SectionElement(text=self.content)
        elif self.type == "synopsis":
            return SynopsisElement(text=self.content)
        elif self.type == "boneyard" or self.type == "note":
            return BoneyardElement(text=self.content)
        elif self.type == "page_break":
            return PageBreakElement()
        elif self.type == "character":
            return DialogueBlock(character_name=self.content, dialogue="", source_ref=self.source_ref)
        elif self.type == "parenthetical":
            return DialogueBlock(character_name="", parenthetical=self.content, dialogue="", source_ref=self.source_ref)
        elif self.type == "heading":
            return ActionElement(text=self.content, source_ref=self.source_ref)
        else:
            return ActionElement(text=self.content, source_ref=self.source_ref)
