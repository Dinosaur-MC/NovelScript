"""Chapter splitter — splits raw novel text into individual chapters.

Strategy (two-tier):
1. **Regex** — match Chinese chapter markers (第X章).  Handles Arabic numerals,
   Chinese numerals, and mixed forms.
2. **LLM fallback** — when the regex produces zero or only one match on a
   large text, the Flash model performs semantic splitting.

Edge cases:
- Empty input      → []
- No markers found → single Chapter wrapping the whole text
"""

from __future__ import annotations

import logging
import re
import textwrap

from cli.llm_router import get_llm
from cli.models import Chapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches Chinese chapter headers:
#   第一章 / 第1章 / 第一二章 / 第123章 / 第零章  etc.
# Also catches optional trailing text (chapter title) on the same line.
_CHAPTER_RE = re.compile(
    r"^\s*第[零一二三四五六七八九十百千\d]+章[^\n]*",
    re.MULTILINE | re.UNICODE,
)

# Minimum average chapter length to avoid triggering LLM fallback when text
# is just a list of chapter headings without body content.
_MIN_CHARS_PER_CHAPTER = 5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def split_chapters(text: str) -> list[Chapter]:
    """Split *text* into a list of Chapter models.

    Args:
        text: The full raw text of the novel.

    Returns:
        Ordered list of Chapter instances (may be empty).
    """
    text = text.strip()
    if not text:
        logger.info("Empty input — returning empty chapter list.")
        return []

    # --- Tier 1: regex split ---
    positions = [(m.start(), m.end(), m.group().strip()) for m in _CHAPTER_RE.finditer(text)]

    if positions:
        chapters = _split_by_positions(text, positions)
        avg_len = sum(len(c.text) for c in chapters) / max(len(chapters), 1)
        # Accept immediately if:
        #  - only one chapter (single marker on short text is almost certainly real), OR
        #  - average body length meets the minimum threshold
        if len(chapters) == 1 or avg_len >= _MIN_CHARS_PER_CHAPTER:
            logger.info(
                "Regex split produced %d chapter(s), avg %.0f chars — accepted.",
                len(chapters),
                avg_len,
            )
            return chapters
        logger.info(
            "Regex found %d marker(s) but chapters too short (avg %.0f chars) — "
            "trying LLM fallback.",
            len(chapters),
            avg_len,
        )

    # --- Tier 2: LLM fallback ---
    return _llm_split(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_by_positions(
    text: str, positions: list[tuple[int, int, str]]
) -> list[Chapter]:
    """Split *text* at the given marker positions into Chapter objects."""
    chapters: list[Chapter] = []
    for idx, (start, end, title) in enumerate(positions):
        # Body starts after the heading line (next newline or end of text)
        after_header = text.find("\n", end)
        body_start = after_header + 1 if after_header != -1 else end

        # Body ends at the next marker, or at EOF
        if idx + 1 < len(positions):
            body_end = positions[idx + 1][0]
        else:
            body_end = len(text)

        body = text[body_start:body_end].strip()
        chapters.append(Chapter(text=body, title=title, index=idx))

    return chapters


def _llm_split(text: str) -> list[Chapter]:
    """Use the Flash model to perform semantic chapter splitting.

    Falls back to a single-chapter wrapper if the LLM call fails.
    Uses JSON mode for reliable structured output.
    """
    from pydantic import BaseModel, Field

    class ChapterItem(BaseModel):
        title: str = Field(..., min_length=1)
        body: str = Field(..., min_length=1)

    class ChapterList(BaseModel):
        chapters: list[ChapterItem] = Field(default_factory=list)

    llm = get_llm("chapter_split", temperature=0.2, json_mode=True)

    prompt = textwrap.dedent("""\
    你是一个小说章节切分助手。请将以下文本按章节切分。

    输出一个 JSON 对象，包含 chapters 数组，每个元素的格式为：
    {"title": "章节标题", "body": "该章节的完整正文"}

    如果文本中没有明确的章节标记，则将整篇文本作为一个章节（chapters 数组中只有一个元素）。

    请以 JSON 格式输出。

    文本内容：
    """) + text[:60000]  # Increased from 12000 — DeepSeek has 128K context

    try:
        resp = llm.invoke(prompt)
        raw = resp.content.strip()  # type: ignore[union-attr]

        # Extract JSON between ```json fences or raw
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0]

        import json

        parsed = json.loads(json_str, strict=False)
        result = ChapterList.model_validate(parsed)

        chapters = [
            Chapter(text=item.body, title=item.title, index=i)
            for i, item in enumerate(result.chapters)
        ]
        logger.info("LLM chapter split produced %d chapter(s).", len(chapters))
        return chapters

    except Exception:
        logger.exception("LLM chapter split failed — wrapping as single chapter.")
        return [Chapter(text=text, title="全文", index=0)]
