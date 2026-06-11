"""Tests for cli.graphrag_builder — KG extraction with JsonOutputParser + JSON mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from cli.graphrag_builder import extract_graph
from cli.models import Chapter, KnowledgeEdge, KnowledgeGraph, KnowledgeNode


_VALID_KG = KnowledgeGraph(
    nodes=[
        KnowledgeNode(id="char_01", name="张三", node_type="character",
                      properties={"traits": ["勇敢"]}),
        KnowledgeNode(id="loc_01", name="京城", node_type="location"),
    ],
    edges=[
        KnowledgeEdge(source_node_id="char_01", target_node_id="loc_01",
                      relation="located_in", weight=0.9),
    ],
)

_VALID_KG_JSON = _VALID_KG.model_dump_json()


class TestExtractGraph:
    def test_empty_chapters_returns_empty_kg(self) -> None:
        result = extract_graph([])
        assert isinstance(result, KnowledgeGraph)
        assert result.nodes == []
        assert result.edges == []

    def test_single_chapter_extracts_kg(self) -> None:
        chapter = Chapter(text="张三住在京城。", title="第一章", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            fake_llm = RunnableLambda(lambda x: AIMessage(content=_VALID_KG_JSON))
            mock_get.return_value = fake_llm
            kg = extract_graph([chapter])
        assert len(kg.nodes) == 2
        assert kg.nodes[0].label == "张三"
        assert len(kg.edges) == 1
        assert kg.edges[0].relation == "located_in"

    def test_json_mode_enabled_on_llm(self) -> None:
        chapter = Chapter(text="test", title="T", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            fake_llm = RunnableLambda(lambda x: AIMessage(content=_VALID_KG_JSON))
            mock_get.return_value = fake_llm
            extract_graph([chapter])
        mock_get.assert_called_once_with(
            "global_extraction", temperature=0.3, json_mode=True
        )

    def test_chain_failure_returns_empty_kg(self) -> None:
        chapter = Chapter(text="test", title="T", index=0)
        with patch("cli.graphrag_builder.get_llm") as mock_get:
            def _raise(_x):
                raise RuntimeError("API error")
            fake_llm = RunnableLambda(_raise)
            mock_get.return_value = fake_llm
            kg = extract_graph([chapter])
            assert kg.nodes == []


# ===========================================================================
# KnowledgeGraph Pydantic model — schema enforced by with_structured_output
# ===========================================================================

class TestKnowledgeGraphModel:
    def test_valid_model(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="char_01", name="张三", node_type="character",
                                 properties={"traits": ["勇敢"]})],
            edges=[KnowledgeEdge(source_node_id="char_01", target_node_id="char_02",
                                 relation="knows", weight=1.0)],
        )
        assert len(kg.nodes) == 1

    def test_missing_node_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeNode(id="char_01", name="张三")

    def test_missing_node_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeNode(name="无ID", node_type="character")

    def test_weight_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeEdge(source_node_id="char_01", target_node_id="char_02",
                          relation="x", weight=99.0)

    def test_edge_default_weight(self) -> None:
        edge = KnowledgeEdge(source_node_id="char_01", target_node_id="char_02",
                             relation="x")
        assert edge.weight == 1.0
