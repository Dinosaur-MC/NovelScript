"""Element type fixer — post-processing corrections for common LLM type errors.

Corrects element misclassifications that the LLM converter commonly makes:
1. Internal monologue marked as ``action`` → ``dialogue_block`` with ``(V.O.)``
2. Spoken self-talk (喃喃自语) → ``dialogue_block``
3. Embedded character name in dialogue content → extracted to character_name + parenthetical
4. Flagging elements with null source_ref (potentially hallucinated)

All fixes operate on the Schema 2.1.0 element types (ActionElement, DialogueBlock, etc.).
"""

from __future__ import annotations

import re

from cli.models import (
    ActionElement,
    BoneyardElement,
    DialogueBlock,
    LyricElement,
    ScriptElement,
    SectionElement,
    SynopsisElement,
    TransitionElement,
)

# Patterns that indicate internal monologue (should be dialogue_block, not action)
_INTERNAL_MONOLOGUE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(.{1,8})内心[：:]\s*(.+)"),
    re.compile(r"^(.{1,8})(?:心中)?(?:暗想|心想|暗忖|心道|暗自\w+|暗骂)[：:]\s*(.+)"),
    re.compile(r"^内心[：:]\s*(.+)"),
    re.compile(r"^(暗想|心想|暗忖|心道|暗骂|心说)[：:]\s*(.+)"),
    re.compile(r"^(.{1,8})心里[（(].+[）)][：:]\s*(.+)"),
]

# Patterns that detect V.O.-worthy narration embedded in action
_VO_INDICATORS: list[str] = [
    "喃喃道", "喃喃自语", "自言自语道", "轻声说", "低声道",
    "默默道", "心里说", "对自己说", "嘀咕道", "嘟囔道",
    "低声骂", "暗骂", "腹诽",
]

# Patterns for spoken self-talk that should be dialogue_block
_SELF_TALK_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(.{1,8})(喃喃道|自言自语道|轻声说|低声道|嘀咕道|嘟囔道)[：:]\s*(.+)"),
]


def fix_element_types(elements: list[ScriptElement]) -> list[ScriptElement]:
    """Correct element type misclassifications.

    Fixes applied:
    1. Internal monologue ActionElement → DialogueBlock with (V.O.)
    2. Spoken self-talk ActionElement → DialogueBlock

    Returns a new list (does not mutate in place).
    """
    result: list[ScriptElement] = []
    for elem in elements:
        if not isinstance(elem, ActionElement) and getattr(elem, "type", "") != "action":
            result.append(elem)
            continue

        content = (getattr(elem, "text", None) or getattr(elem, "content", "")).strip()

        # Fix 1: Internal monologue patterns
        matched = False
        for pattern in _INTERNAL_MONOLOGUE_PATTERNS:
            m = pattern.match(content)
            if m:
                groups = m.groups()
                if len(groups) >= 2 and groups[0] and groups[1]:
                    speaker = groups[0].strip()
                    monologue = groups[1].strip()
                    result.append(DialogueBlock(
                        character_name=speaker,
                        dialogue=monologue,
                        character_extension="(V.O.)" if "V.O." not in monologue else None,
                        source_ref=elem.source_ref,
                    ))
                elif len(groups) >= 1:
                    result.append(DialogueBlock(
                        character_name="",
                        dialogue=groups[0].strip(),
                        character_extension="(V.O.)",
                        source_ref=elem.source_ref,
                    ))
                matched = True
                break

        if matched:
            continue

        # Fix 2: Self-talk indicators
        for pattern in _SELF_TALK_PATTERNS:
            m = pattern.match(content)
            if m and len(m.groups()) >= 3:
                speaker = m.group(1).strip()
                speech = m.group(3).strip()
                result.append(DialogueBlock(
                    character_name=speaker,
                    dialogue=speech,
                    source_ref=elem.source_ref,
                ))
                matched = True
                break

        if matched:
            continue

        # Fix 3: V.O. indicators — extract quoted speech
        for indicator in _VO_INDICATORS:
            if indicator in content:
                quote_match = re.search(r"['\"'「](.+?)['\"'」]", content)
                if quote_match:
                    result.append(DialogueBlock(
                        character_name="",
                        dialogue=quote_match.group(1),
                        character_extension="(V.O.)",
                        source_ref=elem.source_ref,
                    ))
                    matched = True
                    break

        if not matched:
            result.append(elem)

    return result


def split_embedded_character(elements: list[ScriptElement]) -> list[ScriptElement]:
    """Split DialogueBlocks where the speaker name is embedded in dialogue content.

    Detects patterns like ``二喜(大喊)：苦根！`` inside a DialogueBlock's dialogue
    field and extracts the character_name + parenthetical.
    """
    new_elements: list[ScriptElement] = []
    for elem in elements:
        if not isinstance(elem, DialogueBlock) and getattr(elem, "type", "") not in ("dialogue", "dialogue_block"):
            new_elements.append(elem)
            continue

        # Only process if character_name is empty or generic
        content = getattr(elem, "dialogue", None) or getattr(elem, "content", "")
        match = re.match(
            r"^([^(（：:]{1,12})"
            r"\s*"
            r"(?:[（(]([^)）]{1,10})[）)])?\s*"
            r"[：:]\s*"
            r"(.+)$",
            content,
        )
        if match and len(match.group(1)) <= 12:
            character_name = match.group(1).strip()
            parenthetical = match.group(2)
            dialogue_text = match.group(3).strip()

            if _looks_like_character_name(character_name):
                if parenthetical and not parenthetical.startswith("("):
                    parenthetical = f"({parenthetical})"
                if isinstance(elem, DialogueBlock):
                    elem.character_name = character_name
                    elem.dialogue = dialogue_text
                    if parenthetical:
                        elem.parenthetical = parenthetical
                else:
                    # Backward-compat Element: replace with DialogueBlock
                    sr = getattr(elem, "source_ref", None)
                    new_elements.append(DialogueBlock(
                        character_name=character_name,
                        dialogue=dialogue_text,
                        parenthetical=parenthetical,
                        source_ref=sr,
                    ))
                    continue  # skip fallback append

        new_elements.append(elem)

    return new_elements


def _looks_like_character_name(text: str) -> bool:
    """Heuristic: does this text fragment look like a character name?"""
    if len(text) <= 1:
        return False
    if len(text) > 8:
        return False
    if not re.match(r"^[一-鿿·]+$", text):
        return False
    common_openers = {
        "然后", "所以", "但是", "因为", "如果", "虽然", "不过",
        "于是", "接着", "忽然", "突然", "这时", "那时", "只见",
        "因此", "可是", "然而", "而且", "并且",
    }
    if text in common_openers:
        return False
    return True


def flag_missing_source_refs(elements: list[ScriptElement]) -> list[dict]:
    """Identify elements with null source_ref (potentially hallucinated).

    Returns a list of warning dicts, one per element with missing source_ref.
    """
    flagged: list[dict] = []
    for i, elem in enumerate(elements):
        # Extract source_ref across all element types (handles both
        # typed ScriptElement and backward-compat Element shim)
        sr = getattr(elem, "source_ref", None)
        if sr is None:
            elem_type = getattr(elem, "type", "unknown")
            # Get a content preview
            if isinstance(elem, ActionElement) or elem_type == "action":
                preview = (getattr(elem, "text", None) or getattr(elem, "content", ""))[:80]
            elif isinstance(elem, DialogueBlock) or elem_type in ("dialogue", "dialogue_block"):
                preview = (getattr(elem, "dialogue", None) or getattr(elem, "content", ""))[:80]
            elif isinstance(elem, (TransitionElement, LyricElement, BoneyardElement, SectionElement, SynopsisElement)):
                preview = getattr(elem, "text", "")[:80]
            else:
                preview = (getattr(elem, "text", None) or getattr(elem, "dialogue", None) or getattr(elem, "content", ""))[:80]

            flagged.append({
                "index": i,
                "type": elem_type,
                "content_preview": preview,
                "severity": "warning" if (isinstance(elem, ActionElement) or elem_type == "action") else "error",
            })
    return flagged


