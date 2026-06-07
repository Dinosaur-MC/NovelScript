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

from cli.models import Element, Scene, Script


def to_fountain(script: Script) -> str:
    """Convert a Script to Fountain-formatted text.

    Fountain 1.1 spec: https://fountain.io/syntax
    """
    lines: list[str] = []

    # --- Title page ---
    title = script.meta.get("source_file", "Untitled")
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
        lines.append(scene.heading)
        lines.append("")  # blank line after heading (Fountain requirement)

        # Render elements as dialogue-block-aware groups
        fountain_lines = _render_scene_elements(scene.elements)
        # Strip trailing blank lines so we control spacing before ===
        while fountain_lines and fountain_lines[-1] == "":
            fountain_lines.pop()
        lines.extend(fountain_lines)

        # Scene separator (page break) — blank line then === then blank
        lines.append("")
        lines.append("===")
        lines.append("")

    return "\n".join(lines)


def _render_scene_elements(elements: list[Element]) -> list[str]:
    """Render scene elements, preserving Fountain's Character→Dialogue flow.

    In Fountain, Character cues must be immediately followed by Dialogue
    or Parenthetical with NO blank line between them.  This function
    groups consecutive character/parenthetical/dialogue elements into
    "dialogue blocks" and renders them accordingly.
    """
    if not elements:
        return []

    result: list[str] = []
    i = 0

    while i < len(elements):
        elem = elements[i]
        etype = elem.type
        content = elem.content.strip()

        if etype == "character":
            # Start of a dialogue block: Character → Dialogue/Parenthetical chain
            # Fountain: one blank line before character cue
            if result and result[-1] != "":
                result.append("")
            block_lines, i = _render_dialogue_block(elements, i)
            result.extend(block_lines)
            continue

        elif etype == "heading":
            # Sub-heading within a scene
            if result and result[-1] != "":
                result.append("")
            result.append(content)
            result.append("")

        elif etype == "transition":
            # Transition: blank line before, > TO:, blank line after
            if result and result[-1] != "":
                result.append("")
            if content.endswith("TO:") or content.endswith("TO："):
                result.append(content.upper())
            else:
                result.append(f"> {content.upper()}")
            result.append("")

        elif etype == "lyric":
            # Lyric: start with ~
            if result and result[-1] != "":
                result.append("")
            result.append(f"~ {content}")
            result.append("")

        else:
            # action, note, parenthetical (orphaned), dialogue (orphaned), default
            if etype in ("parenthetical", "dialogue"):
                # Orphaned parenthetical/dialogue (no preceding character cue)
                if result and result[-1] != "":
                    result.append("")
                if etype == "parenthetical":
                    result.append(f"({content})" if not content.startswith("(") else content)
                else:
                    result.append(content)
                result.append("")
            else:
                # Action / note — blank line before (if not already blank)
                if result and result[-1] != "":
                    result.append("")
                result.append(content)
                result.append("")

        i += 1

    return result


def _render_dialogue_block(elements: list[Element], start: int) -> tuple[list[str], int]:
    """Render a Character→(Parenthetical|Dialogue)* block.

    Fountain rule: "A Character element is any line entirely in uppercase,
    with one empty line before it and without an empty line after it."

    The blank line BEFORE the character cue is handled by the caller.
    This function renders the character + its following dialogue/parenthetical
    elements with NO blank lines between them.

    Returns:
        (rendered_lines, next_index) where next_index is the index AFTER
        the last element consumed by this block.
    """
    result: list[str] = []
    i = start

    # First element MUST be character
    char_elem = elements[i]
    char_name = char_elem.content.strip().upper()
    result.append(char_name)
    i += 1

    # Consume following dialogue and parenthetical elements (no blank lines)
    while i < len(elements):
        etype = elements[i].type
        content = elements[i].content.strip()

        if etype == "dialogue":
            result.append(content)
            i += 1
        elif etype == "parenthetical":
            paren_content = content if content.startswith("(") else f"({content})"
            result.append(paren_content)
            i += 1
        else:
            # End of dialogue block — next element is action/heading/transition/etc.
            break

    # Blank line after dialogue block ends (Fountain requirement)
    result.append("")

    return result, i
