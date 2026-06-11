"""Scene heading normalizer — deterministic post-processing for slug lines.

Returns a structured ``Heading`` object (Schema §5.5.2) rather than a flat
string.  Handles:

- Chinese → English prefix (内景 → INT., 外景 → EXT.)
- Chinese → English time-of-day (白天 → DAY, etc.)
- MORNING / AFTERNOON → DAY (not in Schema TimeOfDay enum)
- Missing INT./EXT. prefix (heuristic detection)
- Non-standard flashback / dream / montage markers → narrative_mode
- ``.`` forced-heading marker → is_forced
"""

from __future__ import annotations

import re

from cli.models import Heading, IntExt, NarrativeMode, TimeOfDay

# Mapping from Chinese time-of-day to standard English
_TIME_MAP: dict[str, TimeOfDay] = {
    "白天": TimeOfDay.DAY,
    "日": TimeOfDay.DAY,
    "夜晚": TimeOfDay.NIGHT,
    "夜": TimeOfDay.NIGHT,
    "深夜": TimeOfDay.NIGHT,
    "傍晚": TimeOfDay.DUSK,
    "黄昏": TimeOfDay.DUSK,
    "下午": TimeOfDay.DAY,       # Schema has no AFTERNOON → map to DAY
    "午后": TimeOfDay.DAY,
    "清晨": TimeOfDay.DAWN,
    "早晨": TimeOfDay.DAWN,
    "上午": TimeOfDay.DAY,       # Schema has no MORNING → map to DAY
    "几天后": TimeOfDay.LATER,
    "数日后": TimeOfDay.LATER,
    "次日": TimeOfDay.LATER,
    "当晚": TimeOfDay.NIGHT,
    "黎明": TimeOfDay.DAWN,
    "连续": TimeOfDay.CONTINUOUS,
    "稍后": TimeOfDay.LATER,
    "片刻后": TimeOfDay.LATER,
}

# Mapping from Chinese location prefixes to standard slug prefixes
_LOC_PREFIX_MAP: dict[str, IntExt] = {
    "内景": IntExt.INT,
    "外景": IntExt.EXT,
    "内外景": IntExt.INT_EXT,
    "内/外景": IntExt.INT_EXT,
}

# Internal location indicators (heuristic — presence of any word suggests INT.)
_INTERIOR_INDICATORS: list[str] = [
    "房间", "大厅", "屋里", "室内", "亭楼", "阁", "堂",
    "餐厅", "卧室", "厨房", "书房", "牢房", "密室", "青楼",
    "私塾", "店铺", "宫殿", "寝室", "厢房", "客厅", "闺房",
    "练功房", "丹房", "药房", "藏经阁", "祠堂", "澡堂",
    "客栈", "酒楼", "茶馆", "酒馆", "妓院", "当铺",
    "山洞", "洞府", "地宫", "地下", "暗道", "密室",
    "武学阁", "议事大厅", "餐厅",
]

# Special markers → NarrativeMode
_SPECIAL_MAP: dict[str, NarrativeMode] = {
    "FLASHBACK": NarrativeMode.FLASHBACK,
    "闪回": NarrativeMode.FLASHBACK,
    "回忆": NarrativeMode.FLASHBACK,
    "倒叙": NarrativeMode.FLASHBACK,
    "DREAM": NarrativeMode.DREAM,
    "梦境": NarrativeMode.DREAM,
    "梦": NarrativeMode.DREAM,
    "VISION": NarrativeMode.VISION,
    "MONTAGE": NarrativeMode.MONTAGE,
    "蒙太奇": NarrativeMode.MONTAGE,
    "FLASHFORWARD": NarrativeMode.FLASHFORWARD,
}


def normalize_heading(heading: str) -> Heading:
    """Normalize a single scene heading to a structured Heading object.

    Handles:
    - Chinese → English prefix (内景 → INT., 外景 → EXT.)
    - Chinese → English time-of-day (白天 → DAY, etc.)
    - Missing INT./EXT. prefix (heuristic detection)
    - Non-standard flashback/dream markers → narrative_mode
    - ``.`` forced-heading marker → is_forced

    Returns:
        Structured ``Heading`` with parsed sub-fields.
    """
    # Pass through if already a Heading object
    if isinstance(heading, Heading):
        return heading

    original = heading.strip()

    # Step 0: Detect forced heading (Fountain '.' prefix)
    is_forced = False
    if original.startswith("."):
        is_forced = True
        original = original[1:].strip()

    # Step 1: Extract and normalise special markers → narrative_mode
    narrative_mode: NarrativeMode | None = None

    # 1a. Check for prefix-style flashback/memory markers ("闪回 - ", "回忆 - ", etc.)
    for marker, mode in _SPECIAL_MAP.items():
        if len(marker) >= 2 and not marker.startswith("("):
            if original.startswith(marker):
                narrative_mode = mode
                original = original[len(marker):].strip()
                # Remove optional dash/colon separator
                original = re.sub(r"^[-\s:：]+\s*", "", original)
                break

    # 1b. Check for markers in parentheses at end of heading
    special_match = re.search(r"[（(]([^)）]+)[）)]$", original)
    if special_match:
        raw_special = special_match.group(1).strip().upper()
        paren_mode = _SPECIAL_MAP.get(raw_special)
        if paren_mode is None:
            paren_mode = _SPECIAL_MAP.get(special_match.group(1).strip())
        if paren_mode and narrative_mode is None:
            narrative_mode = paren_mode
        original = original[:special_match.start()].strip()

    # Step 2: Detect existing INT./EXT. prefix
    int_ext: IntExt | None = None
    for cn_prefix, en_prefix in _LOC_PREFIX_MAP.items():
        if original.startswith(cn_prefix):
            int_ext = en_prefix
            original = original[len(cn_prefix):].strip()
            # Remove leading punctuation if present
            original = re.sub(r"^[.。,，、]\s*", "", original)
            break

    # Handle shorthand: "内. " or "外. " (Chinese literal with dot)
    if int_ext is None:
        shorthand_m = re.match(r"^(内|外|内外)\s*[.。]\s*", original)
        if shorthand_m:
            shorthands: dict[str, IntExt] = {"内": IntExt.INT, "外": IntExt.EXT, "内外": IntExt.INT_EXT}
            int_ext = shorthands[shorthand_m.group(1)]
            original = original[shorthand_m.end():].strip()

    # Step 3: If no prefix, detect from location semantics
    if int_ext is None:
        m = re.match(r"^(INT\.|EXT\.|INT\./EXT\.|I/E\.)\s+", original)
        if m:
            prefix_str = m.group(1)
            if prefix_str == "I/E.":
                int_ext = IntExt.INT_EXT
            elif prefix_str == "INT./EXT.":
                int_ext = IntExt.INT_EXT
            elif prefix_str.rstrip(".") == "INT":
                int_ext = IntExt.INT
            elif prefix_str.rstrip(".") == "EXT":
                int_ext = IntExt.EXT
            else:
                int_ext = IntExt.EXT  # fallback
            original = original[m.end():].strip()
        else:
            # Heuristic: interior keywords → INT., else EXT.
            if any(indicator in original for indicator in _INTERIOR_INDICATORS):
                int_ext = IntExt.INT
            else:
                int_ext = IntExt.EXT

    # Step 4: Extract and normalise time-of-day
    time_of_day: TimeOfDay = TimeOfDay.DAY  # default
    location = original

    # Match trailing time patterns: "LOCATION - TIME"
    time_match = re.search(
        r"\s*[-—]\s*"
        r"([^\s(（]+)"
        r"(?:\s*[（(][^)）]*[）)])?$",
        location,
    )
    if time_match:
        location = location[:time_match.start()].strip()
        raw_time = time_match.group(1).strip()
        time_of_day = _TIME_MAP.get(raw_time, TimeOfDay.UNKNOWN)
        # Try uppercased for English input
        if time_of_day == TimeOfDay.UNKNOWN:
            raw_upper = raw_time.upper()
            try:
                time_of_day = TimeOfDay(raw_upper)
            except ValueError:
                time_of_day = TimeOfDay.UNKNOWN

    # Step 5: Clean location
    location = re.sub(r"\s*/\s*", " / ", location).strip()
    location = re.sub(r"[.。,，、]$", "", location).strip()
    location = re.sub(r"\s{2,}", " ", location)

    # Step 6: Assemble heading text
    prefix_str = int_ext.value if int_ext else "EXT."
    mode_suffix = f" ({narrative_mode.value})" if narrative_mode else ""
    text = f"{prefix_str} {location} - {time_of_day.value}{mode_suffix}"

    return Heading(
        text=text,
        int_ext=int_ext,
        location=location,
        time_of_day=time_of_day,
        is_forced=is_forced,
        narrative_mode=narrative_mode,
    )
