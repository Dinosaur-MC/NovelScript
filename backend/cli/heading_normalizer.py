"""Scene heading normalizer — deterministic post-processing for slug lines.

Normalises scene headings to conform to the standard screenplay format::

    [INT./EXT.] LOCATION - TIME_OF_DAY [ (FLASHBACK|FLASHFORWARD|DREAM|MONTAGE|LATER|MOMENTS LATER)]

Handles:
- Chinese → English prefix (内景 → INT., 外景 → EXT.)
- Chinese → English time-of-day (白天 → DAY, etc.)
- Missing INT./EXT. prefix (heuristic detection)
- Non-standard flashback markers → (FLASHBACK)
- Multi-location slash clean-up
"""

from __future__ import annotations

import re

# Mapping from Chinese time-of-day to standard English
_TIME_MAP: dict[str, str] = {
    "白天": "DAY",
    "日": "DAY",
    "夜晚": "NIGHT",
    "夜": "NIGHT",
    "深夜": "NIGHT",
    "傍晚": "DUSK",
    "黄昏": "DUSK",
    "午后": "AFTERNOON",
    "下午": "AFTERNOON",
    "清晨": "DAWN",
    "早晨": "MORNING",
    "上午": "MORNING",
    "几天后": "LATER",
    "数日后": "LATER",
    "次日": "LATER",
    "当晚": "NIGHT",
    "黎明": "DAWN",
}

# Mapping from Chinese location prefixes to standard slug prefixes
_LOC_PREFIX_MAP: dict[str, str] = {
    "内景": "INT.",
    "外景": "EXT.",
    "内外景": "INT./EXT.",
    "内/外景": "INT./EXT.",
}

# Internal location indicators (heuristic — presence of any word suggests INT.)
_INTERIOR_INDICATORS: list[str] = [
    "房间", "大厅", "屋里", "室内", "亭楼", "阁", "堂",
    "餐厅", "卧室", "厨房", "书房", "牢房", "密室", "青楼",
    "私塾", "店铺", "宫殿", "寝室", "厢房", "客厅", "闺房",
    "练功房", "丹房", "药房", "藏经阁", "祠堂", "澡堂",
    "客栈", "酒楼", "茶馆", "酒馆", "妓院", "当铺",
    "山洞", "洞府", "地宫", "地下", "暗道", "密室",
]

# Non-standard flashback markers to normalise
_FLASHBACK_MARKERS: list[str] = [
    "闪回 - ", "闪回-", "闪回：",
    "回忆 - ", "回忆：",
    "(闪回)", "（闪回）",
    "闪回 ", "回忆 ",
]


def normalize_heading(heading: str) -> str:
    """Normalize a single scene heading to standard slug-line format.

    Handles:
    - Chinese → English prefix (内景 → INT., 外景 → EXT.)
    - Chinese → English time-of-day (白天 → DAY, etc.)
    - Missing INT./EXT. prefix (heuristic detection)
    - Non-standard flashback markers → (FLASHBACK)
    - Multi-location slash merge

    Returns:
        Normalised heading string, e.g. ``EXT. 练武场 - DAY``.
    """
    original = heading.strip()

    # Step 1: Extract and normalise flashback / dream markers
    flashback = False
    dream = False
    for marker in _FLASHBACK_MARKERS:
        if original.startswith(marker) or marker in original:
            flashback = True
            original = original.replace(marker, "").strip()
            # Also handle trailing Chinese markers
            original = re.sub(r"\s*[（(]闪回[）)]\s*", "", original)

    # Check for dream marker
    if "梦" in original and ("(" in original or "（" in original):
        dream_m = re.search(r"[（(]梦[）)]", original)
        if dream_m:
            dream = True
            original = original[:dream_m.start()] + original[dream_m.end():]
            original = original.strip()

    # Step 2: Detect existing INT./EXT. prefix
    prefix: str | None = None
    for cn_prefix, en_prefix in _LOC_PREFIX_MAP.items():
        if original.startswith(cn_prefix):
            prefix = en_prefix
            original = original[len(cn_prefix):].strip()
            # Remove leading punctuation if present
            original = re.sub(r"^[.。,，、]\s*", "", original)
            break

    # Handle shorthand: "内. " or "外. " (Chinese literal with dot)
    if prefix is None:
        shorthand_m = re.match(r"^(内|外|内外)\s*[.。]\s*", original)
        if shorthand_m:
            shorthands = {"内": "INT.", "外": "EXT.", "内外": "INT./EXT."}
            prefix = shorthands[shorthand_m.group(1)]
            original = original[shorthand_m.end():].strip()

    # Step 3: If no prefix, detect from location semantics
    if prefix is None:
        # Check for standard English prefixes already present
        m = re.match(r"^(INT\.|EXT\.|INT\./EXT\.|I/E\.)\s+", original)
        if m:
            prefix = m.group(1)
            if prefix == "I/E.":
                prefix = "INT./EXT."
            original = original[m.end():].strip()
        else:
            # Heuristic: interior keywords → INT., else EXT.
            if any(indicator in original for indicator in _INTERIOR_INDICATORS):
                prefix = "INT."
            else:
                prefix = "EXT."

    # Step 4: Extract and normalise time-of-day
    time_part = "DAY"  # default
    special = ""
    location = original

    # First, detect special markers already in parentheses
    special_match = re.search(r"[（(]([^)）]+)[）)]$", original)
    if special_match:
        location = original[:special_match.start()].strip()
        raw_special = special_match.group(1).strip().upper()
        # Map known Chinese specials
        _SPECIAL_MAP = {
            "闪回": "FLASHBACK", "回忆": "FLASHBACK", "梦境": "DREAM", "梦": "DREAM",
            "蒙太奇": "MONTAGE", "连续": "CONTINUOUS", "稍后": "LATER",
            "片刻后": "MOMENTS LATER", "后来": "LATER", "倒叙": "FLASHBACK",
        }
        special = _SPECIAL_MAP.get(raw_special, raw_special)

    # Match trailing time patterns: "LOCATION - TIME" or "LOCATION - TIME (SPECIAL)"
    time_match = re.search(
        r"\s*[-—]\s*"
        r"([^\s(（]+)"
        r"(?:\s*[（(]([^)）]+)[）)])?$",
        location,
    )
    if time_match:
        location = location[:time_match.start()].strip()
        raw_time = time_match.group(1).strip()
        time_part = _TIME_MAP.get(raw_time, raw_time.upper())
        if time_match.group(2) and not special:
            special = time_match.group(2)

    # Step 5: Clean location (remove trailing punctuation, normalise spaces)
    location = re.sub(r"\s*/\s*", " / ", location).strip()
    location = re.sub(r"[.。,，、]$", "", location).strip()
    # Dedupe spaces
    location = re.sub(r"\s{2,}", " ", location)

    # Step 6: Assemble
    if flashback:
        special = "FLASHBACK" if not special else f"FLASHBACK, {special}"
    elif dream:
        special = "DREAM" if not special else f"DREAM, {special}"

    if special:
        return f"{prefix} {location} - {time_part} ({special})"
    return f"{prefix} {location} - {time_part}"
