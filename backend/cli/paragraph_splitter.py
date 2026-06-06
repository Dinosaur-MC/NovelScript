"""Paragraph-level text splitter — boundary-aware grouping.

Splits text into paragraph-aligned ``ParagraphGroup`` objects, merging
short paragraphs (≤32 chars) with neighbours so the LLM sees complete
units rather than isolated fragments.
"""

from __future__ import annotations

import re

from cli.models import ParagraphGroup

_SHORT_THRESHOLD = 32  # paragraphs ≤ this many chars are considered "short"


def split_paragraphs(text: str, max_chars: int | None = None) -> list[ParagraphGroup]:
    """Split *text* into paragraph-aligned groups.

    Args:
        text:      The raw text to split.
        max_chars: Optional per-group character budget.  If ``None``,
                   the entire text is returned as a single group.

    Returns:
        Ordered list of ``ParagraphGroup`` objects.  Each group's text
        ends at a paragraph boundary — never mid-sentence.  Short
        paragraphs are merged upward so the LLM never receives isolated
        one-liners.
    """
    stripped = text.strip()
    if not stripped:
        return []

    # 1. Split into individual paragraphs (blank-line separated)
    raw_paras = _split_raw_paragraphs(stripped)
    if not raw_paras:
        return []

    # 2. Merge short paragraphs with their neighbours
    merged = _merge_short(raw_paras)

    if max_chars is None:
        # Single group containing everything
        combined = "\n\n".join(p[0] for p in merged)
        return [ParagraphGroup(
            text=combined,
            offset_start=0,
            offset_end=len(text),
        )]

    # 3. Accumulate into groups within the budget
    groups: list[ParagraphGroup] = []
    batch_texts: list[str] = []
    batch_start: int | None = None
    batch_end: int = 0
    batch_size = 0

    for (para_text, offset_start, offset_end) in merged:
        para_len = len(para_text) + 2  # +2 for "\n\n" separator
        # If adding this paragraph exceeds the budget AND we already
        # have some content, close the current batch.
        if batch_texts and batch_size + para_len > max_chars:
            groups.append(ParagraphGroup(
                text="\n\n".join(batch_texts),
                offset_start=batch_start or 0,
                offset_end=batch_end,
            ))
            batch_texts = []
            batch_start = None
            batch_size = 0

        if batch_start is None:
            batch_start = offset_start
        batch_texts.append(para_text)
        batch_size += para_len
        batch_end = offset_end

    # Final batch
    if batch_texts:
        groups.append(ParagraphGroup(
            text="\n\n".join(batch_texts),
            offset_start=batch_start or 0,
            offset_end=batch_end,
        ))

    return groups


def _split_raw_paragraphs(text: str) -> list[tuple[str, int, int]]:
    """Split *text* on blank-line boundaries, returning (text, start, end) tuples.

    Preserves the original character offsets for source_ref tracing.
    """
    paras: list[tuple[str, int, int]] = []
    # Match paragraphs separated by 2+ newlines
    pattern = re.compile(r"\n{2,}")
    pos = 0
    for match in pattern.finditer(text):
        end = match.start()
        para = text[pos:end].strip()
        if para:
            paras.append((para, pos, end))
        pos = match.end()
    # Last paragraph (after the final blank-line or the entire text)
    if pos < len(text):
        para = text[pos:].strip()
        if para:
            paras.append((para, pos, len(text)))
    return paras


def _merge_short(
    paras: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Merge short (≤32 char) paragraphs with neighbours.

    Strategy: scan left-to-right.  If a paragraph is short and the
    next paragraph exists, merge it forward.  The last paragraph, if
    short, merges backward into the previous one.
    """
    if len(paras) <= 1:
        return list(paras)

    result: list[tuple[str, int, int]] = []
    i = 0
    while i < len(paras):
        text, start, end = paras[i]
        if len(text) > _SHORT_THRESHOLD:
            result.append((text, start, end))
            i += 1
            continue

        # Short paragraph — merge forward if possible
        if i + 1 < len(paras):
            next_text, _, next_end = paras[i + 1]
            merged = text + "\n" + next_text
            result.append((merged, start, next_end))
            i += 2
        elif result:
            # Last paragraph is short → merge with previous
            prev_text, prev_start, _ = result[-1]
            merged = prev_text + "\n" + text
            result[-1] = (merged, prev_start, end)
            i += 1
        else:
            # Only one short paragraph in the entire text
            result.append((text, start, end))
            i += 1

    return result
