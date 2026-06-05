"""Tests for cli.graphrag_builder — KG extraction with with_structured_output()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from cli.graphrag_builder import extract_graph
from cli.models import Chapter, KnowledgeEdge, KnowledgeGraph, KnowledgeNode


_VALID_KG = KnowledgeGraph(
    nodes=[
        KnowledgeNode(id="n_01", name="张三", node_type="character",
                      properties={"traits": ["勇敢"]}),
        KnowledgeNode(id="n_02", name="京城", node_type="location"),
    ],
    edges=[
        KnowledgeEdge(source_node_id="n_01", target_node_id="n_02",
                      relation="located_in", weight=0.9),
    ],
)


class TestExtractGraph:
    def test_empty_chapters_returns_empty_kg(self) -> None:
        result = extract_graph([])
        assert isinstance(result, KnowledgeGraph)
        assert result.nodes == []
        assert result.edges == []

    def test_single_chapter_extracts_kg(self) -> None:
        chapter = Chapter(text="张三住在京城。", title="第一章", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.return_value = _VALID_KG
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            kg = extract_graph([chapter])
        assert len(kg.nodes) == 2
        assert kg.nodes[0].name == "张三"
        assert len(kg.edges) == 1
        assert kg.edges[0].relation == "located_in"

    def test_with_structured_output_called(self) -> None:
        chapter = Chapter(text="test", title="T", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.return_value = _VALID_KG
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            extract_graph([chapter])
        mock_llm.with_structured_output.assert_called_once_with(KnowledgeGraph)

    def test_chain_failure_returns_empty_kg(self) -> None:
        chapter = Chapter(text="test", title="T", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.side_effect = RuntimeError("API error")
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            kg = extract_graph([chapter])
            assert kg.nodes == []


# ===========================================================================
# KnowledgeGraph Pydantic model — schema enforced by with_structured_output
# ===========================================================================

class TestKnowledgeGraphModel:
    def test_valid_model(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="n_01", name="张三", node_type="character",
                                 properties={"traits": ["勇敢"]})],
            edges=[KnowledgeEdge(source_node_id="n_01", target_node_id="n_02",
                                 relation="knows", weight=1.0)],
        )
        assert len(kg.nodes) == 1

    def test_missing_node_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeNode(id="n_01", name="张三")

    def test_missing_node_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeNode(name="无ID", node_type="character")

    def test_weight_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeEdge(source_node_id="n_01", target_node_id="n_02",
                          relation="x", weight=99.0)

    def test_edge_default_weight(self) -> None:
        edge = KnowledgeEdge(source_node_id="n_01", target_node_id="n_02",
                             relation="x")
        assert edge.weight == 1.0
