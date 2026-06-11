"""Fountain exporter — converts a Script to Fountain 1.1 format.

Fountain is an industry-standard plain-text screenplay markup format.
Spec: https://fountain.io/syntax

Key rules enforced:
- Scene headings: preceded and followed by blank lines
- Character cues: UPPERCASE, one blank line before, NONE after
- Dialogue: immediately follows Character or Parenthetical (no blank line)
- Parenthetical: immediately follows Character or Dialogue, wrapped in ()
- Transitions: uppercase, ends in TO:, preceded and followed by blank lines
- Action: default paragraph, followed by blank line
- Page breaks: ``===`` on its own line

Compatible with: Final Draft, Highland 2, Fade In, Slugline, and VS Code
Fountain extension.
"""

from __future__ import annotations

from cli.models import (
    ActionElement,
    BoneyardElement,
    DialogueBlock,
    LyricElement,
    Scene,
    Script,
    ScriptElement,
    SectionElement,
    SynopsisElement,
    TransitionElement,
)


def to_fountain(script: Script) -> str:
    """Convert a Script to Fountain-formatted text.

    Fountain 1.1 spec: https://fountain.io/syntax
    """
    lines: list[str] = []

    # --- Title page ---
    title = script.title_page.title or script.meta.get("source_file", "Untitled")
    lines.append(f"Title: {title}")
    lines.append("Credit: Adapted by NovelScript Pipeline")
    lines.append("Source: Novel → Script Conversion")
    lines.append(f"Notes: {script.meta.get('chapter_count', 0)} chapters, "
                 f"{script.meta.get('scene_count', 0)} scenes")
    lines.append("")
    lines.append("===")
    lines.append("")

    for i, scene in enumerate(script.scenes):
        # Scene heading — preceded by a blank line
        if i > 0:
            lines.append("")
        heading_text = scene.heading.text if hasattr(scene.heading, "text") else str(scene.heading)
        lines.append(heading_text)
        lines.append("")  # blank line after heading (Fountain requirement)

        # Render elements
        fountain_lines = _render_scene_elements(scene.elements)
        while fountain_lines and fountain_lines[-1] == "":
            fountain_lines.pop()
        lines.extend(fountain_lines)

        # Scene separator (page break)
        lines.append("")
        lines.append("===")
        lines.append("")

    return "\n".join(lines)


def _render_scene_elements(elements: list[ScriptElement]) -> list[str]:
    """Render scene elements in Fountain format."""
    if not elements:
        return []

    result: list[str] = []

    for elem in elements:
        if isinstance(elem, DialogueBlock):
            # Character → Parenthetical? → Dialogue
            if result and result[-1] != "":
                result.append("")
            char_line = elem.character_name.upper()
            if elem.character_extension:
                char_line += f" {elem.character_extension}"
            result.append(char_line)
            if elem.parenthetical:
                p = elem.parenthetical
                result.append(p if p.startswith("(") else f"({p})")
            result.append(elem.dialogue)
            result.append("")  # blank after block

        elif isinstance(elem, ActionElement):
            if result and result[-1] != "":
                result.append("")
            text = elem.text
            if elem.is_forced:
                text = f"!{text}"
            if elem.is_centered:
                text = f"> {text} <"
            result.append(text)
            result.append("")

        elif isinstance(elem, TransitionElement):
            if result and result[-1] != "":
                result.append("")
            text = elem.text
            if text.endswith("TO:") or text.endswith("TO："):
                result.append(text.upper())
            else:
                result.append(f"> {text.upper()}")
            result.append("")

        elif isinstance(elem, LyricElement):
            if result and result[-1] != "":
                result.append("")
            result.append(f"~ {elem.text}")
            result.append("")

        elif isinstance(elem, SectionElement):
            if result and result[-1] != "":
                result.append("")
            result.append(f"{'#' * elem.level} {elem.text}")
            result.append("")

        elif isinstance(elem, SynopsisElement):
            if result and result[-1] != "":
                result.append("")
            result.append(f"= {elem.text}")
            result.append("")

        elif isinstance(elem, BoneyardElement):
            if result and result[-1] != "":
                result.append("")
            result.append(f"/* {elem.text} */")
            result.append("")

        # PageBreakElement and unknowns are silently skipped

    return result
