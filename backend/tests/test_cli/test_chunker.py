"""Tests for cli.chunker — chapter splitting logic.

Covers:
- Regex-based splitting (Tier 1)
- Edge cases: empty input, no markers, single chapter
"""

from __future__ import annotations

from cli.chunker import split_chapters


# ===========================================================================
# Regex-based splitting
# ===========================================================================


class TestRegexChapterSplitting:
    """Happy-path tests for the primary regex splitter."""

    def test_regex_two_chapters(self) -> None:
        text = (
            "第一章 序章\n"
            "这是第一章的正文内容。\n"
            "第二章 开端\n"
            "这是第二章的正文内容。\n"
        )
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0].title == "第一章 序章"
        assert "第一章的正文" in chapters[0].text
        assert chapters[1].title == "第二章 开端"
        assert "第二章的正文" in chapters[1].text
        assert chapters[0].index == 0
        assert chapters[1].index == 1

    def test_regex_arabic_numerals(self) -> None:
        text = (
            "第1章 开始\n"
            "正文内容A。\n"
            "第2章 继续\n"
            "正文内容B。\n"
        )
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0].title == "第1章 开始"
        assert chapters[1].title == "第2章 继续"

    def test_regex_chinese_numerals(self) -> None:
        text = (
            "第一十章 最终\n"
            "最终章的正文。\n"
        )
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0].title == "第一十章 最终"

    def test_regex_single_chapter(self) -> None:
        text = "第一章 唯一的章节\n正文内容。"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0].title == "第一章 唯一的章节"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge-case and fallback behaviour."""

    def test_empty_input_returns_empty_list(self) -> None:
        chapters = split_chapters("")
        assert chapters == []

    def test_whitespace_only_returns_empty(self) -> None:
        chapters = split_chapters("   \n  \t  ")
        assert chapters == []

    def test_no_markers_returns_one_chapter(self) -> None:
        """When text has no chapter markers, it returns a single Chapter."""
        text = "这是一段没有任何章节标记的文本。\n它应该被当作一个完整的章节。"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0].index == 0
        assert text in chapters[0].text

    def test_markers_with_tiny_bodies_falls_back(self) -> None:
        """When markers produce chapters shorter than the minimum, LLM fallback
        kicks in.  Since no API key is present in tests, the fallback wraps
        as a single chapter."""
        text = "第一章\nx\n第二章\ny\n"
        # Each chapter body is ~1 char — below the 50-char threshold.
        # The LLM fallback will fail (no API key), so we get 1 chapter.
        chapters = split_chapters(text)
        # With no DEEPSEEK_API_KEY, LLM fallback fails → wraps as single chapter
        assert len(chapters) == 1
