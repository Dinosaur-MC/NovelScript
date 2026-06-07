"""Element type fixer — post-processing corrections for common LLM type errors.

Corrects element misclassifications that the LLM converter commonly makes:
1. Internal monologue marked as ``action`` → ``dialogue`` with ``(V.O.)``
2. Spoken self-talk (喃喃自语) → ``dialogue``
3. Embedded character name in dialogue content → split into character + parenthetical + dialogue
4. Flagging elements with null source_ref (potentially hallucinated)
"""

from __future__ import annotations

import re

from cli.models import Element

# Patterns that indicate internal monologue (should be dialogue, not action)
_INTERNAL_MONOLOGUE_PATTERNS: list[re.Pattern] = [
    # 李浮尘内心：xxx
    re.compile(r"^(.{1,8})内心[：:]\s*(.+)"),
    # 李浮尘心中暗想：xxx / 李浮尘心想：xxx
    re.compile(r"^(.{1,8})(?:心中)?(?:暗想|心想|暗忖|心道|暗自\w+|暗骂)[：:]\s*(.+)"),
    # xxx内心：xxx (无主语)
    re.compile(r"^内心[：:]\s*(.+)"),
    # 暗想：xxx / 心道：xxx (leading with thought verb)
    re.compile(r"^(暗想|心想|暗忖|心道|暗骂|心说)[：:]\s*(.+)"),
    # 心里（xxx）：yyy — thought with parenthetical
    re.compile(r"^(.{1,8})心里[（(].+[）)][：:]\s*(.+)"),
]

# Patterns that detect V.O.-worthy narration embedded in action
_VO_INDICATORS: list[str] = [
    "喃喃道", "喃喃自语", "自言自语道", "轻声说", "低声道",
    "默默道", "心里说", "对自己说", "嘀咕道", "嘟囔道",
    "低声骂", "暗骂", "腹诽",
]

# Patterns for spoken self-talk that should be dialogue
_SELF_TALK_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(.{1,8})(喃喃道|自言自语道|轻声说|低声道|嘀咕道|嘟囔道)[：:]\s*(.+)"),
]


def fix_element_types(elements: list[Element]) -> list[Element]:
    """Correct element type misclassifications in place.

    Fixes applied:
    1. Internal monologue marked as ``action`` → ``dialogue`` with ``(V.O.)``
    2. Spoken self-talk (喃喃自语) → ``dialogue``
    3. Dialogue with embedded character name → split

    Returns the modified elements list (mutated in place).
    """
    for elem in elements:
        if elem.type != "action":
            continue

        content = elem.content.strip()

        # Fix 1: Internal monologue patterns
        matched = False
        for pattern in _INTERNAL_MONOLOGUE_PATTERNS:
            m = pattern.match(content)
            if m:
                groups = m.groups()
                if len(groups) >= 2 and groups[0] and groups[1]:
                    # Has separate speaker and monologue content
                    speaker = groups[0].strip()
                    monologue = groups[1].strip()
                    elem.type = "dialogue"
                    elem.content = f"({speaker}, V.O.) {monologue}"
                elif len(groups) >= 1:
                    # No explicit speaker
                    elem.type = "dialogue"
                    elem.content = f"(V.O.) {groups[0].strip()}"
                matched = True
                break

        if matched:
            continue

        # Fix 2: Self-talk indicators (spoken aloud, should be dialogue)
        for pattern in _SELF_TALK_PATTERNS:
            m = pattern.match(content)
            if m and len(m.groups()) >= 3:
                speaker = m.group(1).strip()
                speech = m.group(3).strip()
                elem.type = "dialogue"
                elem.content = f"{speaker}: {speech}"
                matched = True
                break

        if matched:
            continue

        # Fix 3: V.O. indicators — extract quoted speech
        for indicator in _VO_INDICATORS:
            if indicator in content:
                # Extract quoted speech if present
                quote_match = re.search(r"['\"'「](.+?)['\"'」]", content)
                if quote_match:
                    elem.type = "dialogue"
                    elem.content = f"(V.O.) {quote_match.group(1)}"
                    matched = True
                    break

    return elements


def split_embedded_character(elements: list[Element]) -> list[Element]:
    """Split elements where the speaker name is embedded in content.

    Detects patterns like ``二喜(大喊)：苦根！`` and splits into:
        - type: character, content: 二喜
        - type: parenthetical, content: 大喊
        - type: dialogue, content: 苦根！

    Also handles ``福贵(对牛)：今天有庆...`` and similar.
    """
    new_elements: list[Element] = []
    for elem in elements:
        if elem.type != "dialogue":
            new_elements.append(elem)
            continue

        # Pattern: "Name(emotion)：content" or "Name：content"
        # Use non-greedy name match that stops before paren or colon
        match = re.match(
            r"^([^(（：:]{1,12})"          # name: non-paren/colon chars only
            r"\s*"
            r"(?:[（(]([^)）]{1,10})[)）])?\s*"
            r"[：:]\s*"
            r"(.+)$",
            elem.content,
        )
        if match and len(match.group(1)) <= 12:
            character_name = match.group(1).strip()
            parenthetical = match.group(2)
            dialogue_text = match.group(3).strip()

            # Only split if the "name" looks like a character, not a sentence start
            if _looks_like_character_name(character_name):
                char_elem = Element(
                    type="character",
                    content=character_name,
                    source_ref=elem.source_ref,
                )
                new_elements.append(char_elem)

                if parenthetical:
                    par_elem = Element(
                        type="parenthetical",
                        content=parenthetical,
                        source_ref=elem.source_ref,
                    )
                    new_elements.append(par_elem)

                dial_elem = Element(
                    type="dialogue",
                    content=dialogue_text,
                    source_ref=elem.source_ref,
                )
                new_elements.append(dial_elem)
                continue

        new_elements.append(elem)

    return new_elements


def _looks_like_character_name(text: str) -> bool:
    """Heuristic: does this text fragment look like a character name?"""
    # Character names are usually 2-4 Chinese characters, or known patterns
    if len(text) <= 1:
        return False
    if len(text) > 8:
        return False
    # Contains only Chinese characters (and maybe a period/interpunct for titles)
    if not re.match(r"^[一-鿿·]+$", text):
        return False
    # Not a common dialogue opener or grammatical particle
    common_openers = {
        "然后", "所以", "但是", "因为", "如果", "虽然", "不过",
        "于是", "接着", "忽然", "突然", "这时", "那时", "只见",
        "因此", "可是", "然而", "而且", "并且",
    }
    if text in common_openers:
        return False
    return True


def flag_missing_source_refs(elements: list[Element]) -> list[dict]:
    """Identify elements with null source_ref (potentially hallucinated).

    Returns a list of warning dicts, one per element with missing source_ref.
    """
    flagged: list[dict] = []
    for i, elem in enumerate(elements):
        if elem.source_ref is None:
            flagged.append({
                "index": i,
                "type": elem.type,
                "content_preview": elem.content[:80],
                "severity": "warning" if elem.type == "action" else "error",
            })
    return flagged
