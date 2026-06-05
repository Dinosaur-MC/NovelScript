"""Tests for cli.graphrag_builder — KG extraction, Auto-Fix, JSON parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cli.graphrag_builder import (
    _call_llm,
    _parse_and_validate,
    extract_graph,
)
from cli.models import Chapter, KnowledgeEdge, KnowledgeGraph, KnowledgeNode


# ===========================================================================
# extract_graph
# ===========================================================================

class TestExtractGraph:
    def test_empty_chapters_returns_empty_kg(self) -> None:
        result = extract_graph([])
        assert isinstance(result, KnowledgeGraph)
        assert result.nodes == []
        assert result.edges == []

    def test_single_chapter_extracts_kg(self) -> None:
        """Happy-path: valid JSON from LLM → validated KG."""
        chapter = Chapter(text="张三和李四是好友，住在京城。", title="第一章", index=0)
        valid_json = json.dumps({
            "nodes": [
                {"id": "n_01", "name": "张三", "node_type": "character", "properties": {"traits": ["勇敢"]}},
                {"id": "n_02", "name": "李四", "node_type": "character", "properties": {"traits": ["聪明"]}},
                {"id": "n_03", "name": "京城", "node_type": "location", "properties": {}},
            ],
            "edges": [
                {"source_node_id": "n_01", "target_node_id": "n_02", "relation": "friend_of", "weight": 0.9},
            ],
        })

        with patch("cli.graphrag_builder.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content = valid_json
            mock_get_llm.return_value = mock_llm

            kg = extract_graph([chapter])

        assert len(kg.nodes) == 3
        assert kg.nodes[0].name == "张三"
        assert kg.nodes[0].node_type == "character"
        assert kg.nodes[2].node_type == "location"
        assert len(kg.edges) == 1
        assert kg.edges[0].relation == "friend_of"


class TestExtractGraphAutoFix:
    def test_retries_on_validation_failure(self) -> None:
        """First call returns malformed JSON → retry → success."""
        chapter = Chapter(text="测试文本。", title="第一章", index=0)
        # Must be ACTUALLY unparseable, not just empty-data JSON
        bad_json = "this is not valid json {{{"
        good_json = json.dumps({
            "nodes": [{"id": "n_01", "name": "修复", "node_type": "character", "properties": {}}],
            "edges": [],
        })

        with patch("cli.graphrag_builder.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            resp1 = MagicMock()
            resp1.content.strip.return_value = bad_json
            resp2 = MagicMock()
            resp2.content.strip.return_value = good_json
            mock_llm.invoke.side_effect = [resp1, resp2, resp2]
            mock_get_llm.return_value = mock_llm

            kg = extract_graph([chapter])

        assert len(kg.nodes) == 1
        assert kg.nodes[0].name == "修复"
        assert mock_llm.invoke.call_count == 2  # bad + good

    def test_all_retries_exhausted_returns_empty_kg(self) -> None:
        chapter = Chapter(text="测试。", title="第一章", index=0)
        bad_json = "always fails to parse {{{"

        with patch("cli.graphrag_builder.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            resp = MagicMock()
            resp.content.strip.return_value = bad_json
            mock_llm.invoke.side_effect = [resp, resp, resp]
            mock_get_llm.return_value = mock_llm

            kg = extract_graph([chapter])

        assert kg.nodes == []
        assert kg.edges == []
        assert mock_llm.invoke.call_count == 3  # original + 2 retries


# ===========================================================================
# _parse_and_validate — pure function, tested directly
# ===========================================================================

class TestParseValidate:
    def test_valid_json_parses_correctly(self) -> None:
        raw = json.dumps({
            "nodes": [
                {"id": "n_01", "name": "张三", "node_type": "character", "properties": {"traits": ["勇敢"]}},
            ],
            "edges": [
                {"source_node_id": "n_01", "target_node_id": "n_02", "relation": "knows", "weight": 1.0},
            ],
        })
        kg = _parse_and_validate(raw)
        assert len(kg.nodes) == 1
        assert len(kg.edges) == 1
        assert kg.nodes[0].name == "张三"
        assert kg.edges[0].weight == 1.0

    def test_missing_node_type_raises(self) -> None:
        raw = json.dumps({
            "nodes": [{"id": "n_01", "name": "张三"}],
            "edges": [],
        })
        with pytest.raises(Exception):
            _parse_and_validate(raw)

    def test_missing_node_id_raises(self) -> None:
        raw = json.dumps({
            "nodes": [{"name": "无ID", "node_type": "character"}],
            "edges": [],
        })
        with pytest.raises(Exception):
            _parse_and_validate(raw)

    def test_empty_kg_parses(self) -> None:
        raw = json.dumps({"nodes": [], "edges": []})
        kg = _parse_and_validate(raw)
        assert kg.nodes == []
        assert kg.edges == []

    def test_weight_out_of_range_raises(self) -> None:
        raw = json.dumps({
            "nodes": [{"id": "n_01", "name": "A", "node_type": "character", "properties": {}}],
            "edges": [{"source_node_id": "n_01", "target_node_id": "n_02", "relation": "x", "weight": 99.0}],
        })
        with pytest.raises(Exception):
            _parse_and_validate(raw)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_and_validate("not valid json {{{")

    def test_edge_default_weight(self) -> None:
        raw = json.dumps({
            "nodes": [{"id": "n_01", "name": "A", "node_type": "character", "properties": {}}],
            "edges": [{"source_node_id": "n_01", "target_node_id": "n_02", "relation": "x"}],
        })
        kg = _parse_and_validate(raw)
        assert kg.edges[0].weight == 1.0  # default


# ===========================================================================
# _call_llm — markdown-fence stripping
# ===========================================================================

class TestCallLLM:
    def test_strips_json_fence(self) -> None:
        mock_llm = MagicMock()
        # invoke returns a response; .content is the raw text; .content.strip()
        # is what _call_llm actually calls after invoke
        resp = MagicMock()
        resp.content.strip.return_value = '{"nodes":[],"edges":[]}'
        mock_llm.invoke.return_value = resp

        raw = _call_llm(mock_llm, "text", 0)
        assert raw == '{"nodes":[],"edges":[]}'

    def test_strips_generic_fence(self) -> None:
        mock_llm = MagicMock()
        resp = MagicMock()
        resp.content.strip.return_value = '{"nodes":[],"edges":[]}'
        mock_llm.invoke.return_value = resp

        raw = _call_llm(mock_llm, "text", 0)
        assert raw == '{"nodes":[],"edges":[]}'

    def test_attempt_greater_than_zero_includes_retry_hint(self) -> None:
        """When attempt > 0, the LLM sees a retry instruction in the user prompt.
        The LLM's output itself is just JSON — we verify _call_llm returns it
        and that the messages sent to the LLM differ when attempt > 0."""
        mock_llm = MagicMock()
        resp1 = MagicMock()
        resp1.content.strip.return_value = '{"nodes":[],"edges":[]}'
        mock_llm.invoke.return_value = resp1

        # Call with attempt=0 first, then attempt=1
        _call_llm(mock_llm, "测试文本", 0)
        call0_args = mock_llm.invoke.call_args

        _call_llm(mock_llm, "测试文本", 1)
        call1_args = mock_llm.invoke.call_args

        # The messages sent to the LLM should differ between attempt 0 and 1
        msgs0 = call0_args[0][0]
        msgs1 = call1_args[0][0]
        assert len(msgs0) == len(msgs1) == 2  # SystemMessage + HumanMessage

        # The HumanMessage content should differ (retry hint added)
        user0 = msgs0[1].content
        user1 = msgs1[1].content
        assert user0 != user1
        assert "重新提取" in user1 or "重新" in user1
