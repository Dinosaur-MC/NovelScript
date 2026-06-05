"""Tests for cli.rag_builder — FAISS index, search, keyword fallback."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from cli.models import Chapter
from cli.rag_builder import _keyword_fallback, build_index, search


# ===========================================================================
# build_index
# ===========================================================================

class TestBuildIndex:
    def test_empty_chapters_returns_none(self) -> None:
        assert build_index([]) is None

    def test_faiss_failure_returns_none(self) -> None:
        chapters = [Chapter(text="测试文本", title="第一章", index=0)]
        with patch("cli.rag_builder.FAISS") as mock_faiss:
            mock_faiss.from_documents.side_effect = RuntimeError("API down")
            result = build_index(chapters)
            assert result is None

    def test_no_api_key_returns_none_gracefully(self) -> None:
        chapters = [Chapter(text="测试", title="第一章", index=0)]
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with patch("cli.rag_builder.OpenAIEmbeddings") as mock_emb:
                mock_emb.return_value = MagicMock()
                # Embeddings creation succeeds but FAISS may fail
                with patch("cli.rag_builder.FAISS") as mock_faiss:
                    mock_faiss.from_documents.side_effect = Exception("no key")
                    result = build_index(chapters)
                    assert result is None


# ===========================================================================
# search
# ===========================================================================

class TestSearch:
    def test_none_index_calls_keyword_fallback(self) -> None:
        result = search(None, "hello world", k=2)
        assert result == []  # no texts to search

    def test_search_failure_falls_back_to_keyword(self) -> None:
        mock_index = MagicMock()
        mock_index.similarity_search.side_effect = RuntimeError("crash")
        chapters = [
            Chapter(text="hello world foo", title="T1", index=0),
            Chapter(text="bar baz qux", title="T2", index=1),
        ]
        with patch("cli.rag_builder._keyword_fallback") as mock_kw:
            mock_kw.return_value = ["result1"]
            result = search(mock_index, "query", k=3)
            mock_kw.assert_called_once()
            assert result == ["result1"]


# ===========================================================================
# _keyword_fallback — internal function, tested directly
# ===========================================================================

class TestKeywordFallback:
    def test_empty_texts_returns_empty(self) -> None:
        assert _keyword_fallback("hello", [], 3) == []

    def test_matches_by_character_overlap(self) -> None:
        texts = ["hello world x y", "foo bar baz", "hello hello z z"]
        results = _keyword_fallback("hello", texts, k=2)
        # Both "hello hello z z" and "hello world x y" each contain 'h','e','l','o'
        # — they tie on char overlap, order depends on input list stability.
        # Just verify we get 2 results and they're from the right subset.
        assert len(results) == 2
        assert "hello hello" in results[0] or "hello world" in results[0]
        assert "hello hello" in results[1] or "hello world" in results[1]

    def test_respects_k_limit(self) -> None:
        texts = ["a x", "b x", "c x", "d x"]
        results = _keyword_fallback("x", texts, k=2)
        assert len(results) == 2

    def test_chinese_characters(self) -> None:
        texts = ["张三走进大殿", "李四在花园散步", "王五骑马"]
        results = _keyword_fallback("张三", texts, k=1)
        assert results[0] == "张三走进大殿"


# ===========================================================================
# Search with mock FAISS index
# ===========================================================================

class TestSearchWithMockIndex:
    def test_successful_similarity_search(self) -> None:
        from langchain_core.documents import Document

        mock_index = MagicMock()
        mock_index.similarity_search.return_value = [
            Document(page_content="result one", metadata={}),
            Document(page_content="result two", metadata={}),
        ]
        result = search(mock_index, "query", k=2)
        assert result == ["result one", "result two"]

    def test_empty_similarity_results(self) -> None:
        mock_index = MagicMock()
        mock_index.similarity_search.return_value = []
        result = search(mock_index, "query", k=3)
        assert result == []
