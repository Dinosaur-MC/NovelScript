"""Chapter summarizer — generates objective per-chapter summaries.

Each chapter is summarized independently so the summaries can be computed
in parallel.  The result is a concise (100–200 char) plain-text summary
of *what happened* — no interpretation, no foreshadowing, no formatting.
"""

from __future__ import annotations

import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from cli.llm_router import get_llm, invoke_llm_with_retry
from cli.models import Chapter

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 200

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
你是一个客观的事实记录员。请用简洁的语言概括以下章节中发生的事情。

要求：
- 仅描述本章内实际发生的事件和动作
- 不要推论、评价、预测或总结深层含义
- 不要使用"这一章讲述了""本章"等元描述
- 以一段连续的自然语言段落输出，不要使用任何列表标记（如 -、•、1.）
- 不要使用 Markdown 格式
- 控制输出在 150 字以内"""),
    ("human", "请概括以下章节内容（以一段话形式输出）：\n\n【章节标题】{title}\n\n【章节正文】{text}"),
])

# Strip markdown bullet-marker prefixes for consistent plain-text output.
_BULLET_RE = re.compile(r"^\s*[-•*]\s*", re.MULTILINE)


def summarize_chapter(chapter: Chapter, max_chars: int = 10_000) -> str:
    """Generate an objective event-summary for *chapter*.

    Args:
        chapter:  The chapter to summarize.
        max_chars: Max characters of chapter text to send (default 10k).
                   The first *max_chars* chars are used; the tail is
                   truncated for summarisation only, not for conversion.

    Returns:
        A ~100–200 character plain-text summary string, or ``""`` on failure.
    """
    if not chapter.text.strip():
        return ""

    llm = get_llm("chapter_summary", temperature=0.1, json_mode=False)

    try:
        resp = invoke_llm_with_retry(llm, _PROMPT.invoke({
            "title": chapter.title,
            "text": chapter.text[:max_chars],
        }), "chapter_summary")
        raw = resp.content.strip()  # type: ignore[union-attr]
        # Normalise: strip markdown bullet markers introduced by Flash
        raw = _BULLET_RE.sub("", raw)
        # Collapse multiple newlines into a single space for a single paragraph
        raw = " ".join(line.strip() for line in raw.splitlines() if line.strip())
        summary = raw[:_SUMMARY_MAX_CHARS]
        logger.debug("Chapter %d summary: %s", chapter.index, summary[:60])
        return summary
    except Exception:
        logger.exception("Failed to summarize chapter %d — returning empty.", chapter.index)
        return ""
