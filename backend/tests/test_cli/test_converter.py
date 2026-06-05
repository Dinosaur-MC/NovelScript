"""Tests for cli.converter — chapter→scene, source_ref injection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cli.converter import _inject_source_refs, _summarize_kg, SceneList, convert_chapter
from cli.models import (
    Chapter, Element, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, Scene,
)


@pytest.fixture
def sample_chapter() -> Chapter:
    return Chapter(text="张三大步走进大殿，朗声道：「臣有本启奏！」", title="第一章 序章", index=0)


@pytest.fixture
def sample_kg() -> KnowledgeGraph:
    return KnowledgeGraph(
        nodes=[
            KnowledgeNode(id="n_01", name="张三", node_type="character",
                          properties={"aliases": ["三哥"], "traits": ["勇敢"]}),
            KnowledgeNode(id="n_02", name="大殿", node_type="location",
                          properties={"description": "皇宫正殿"}),
        ],
        edges=[
            KnowledgeEdge(source_node_id="n_01", target_node_id="n_02",
                          relation="located_in", weight=0.9),
        ],
    )


class TestSummarizeKG:
    def test_empty_kg(self) -> None:
        assert "为空" in _summarize_kg(KnowledgeGraph())

    def test_summary_includes_characters_and_locations(self, sample_kg: KnowledgeGraph) -> None:
        result = _summarize_kg(sample_kg)
        assert "张三" in result
        assert "大殿" in result

    def test_characters_with_aliases(self) -> None:
        kg = KnowledgeGraph(nodes=[
            KnowledgeNode(id="n_01", name="张三", node_type="character",
                          properties={"aliases": ["三哥", "三爷"]}),
        ])
        assert "三哥" in _summarize_kg(kg)


class TestInjectSourceRefs:
    def test_injects_when_content_found(self, sample_chapter: Chapter) -> None:
        scene = Scene(scene_id="s_000", heading="x", location="x", time_of_day="x",
                      elements=[Element(type="action", content="张三大步走进大殿")],
                      characters_present=[])
        scenes = _inject_source_refs([scene], sample_chapter)
        assert scenes[0].elements[0].source_ref["confidence"] == "exact"

    def test_content_not_found_gets_estimated(self, sample_chapter: Chapter) -> None:
        scene = Scene(scene_id="s_000", heading="x", location="x", time_of_day="x",
                      elements=[Element(type="dialogue", content="这句话不在原文中")],
                      characters_present=[])
        scenes = _inject_source_refs([scene], sample_chapter)
        assert scenes[0].elements[0].source_ref["confidence"] == "estimated"

    def test_preserves_existing_source_ref(self) -> None:
        ch = Chapter(text="any", title="T", index=1)
        scene = Scene(scene_id="s_001", heading="x", location="x", time_of_day="x",
                      elements=[Element(type="action", content="any",
                                        source_ref={"chapter_id": "existing", "offset": [1, 2]})],
                      characters_present=[])
        scenes = _inject_source_refs([scene], ch)
        assert scenes[0].elements[0].source_ref == {"chapter_id": "existing", "offset": [1, 2]}


_MOCK_SCENE_LIST = SceneList(scenes=[
    Scene(scene_id="s_000", heading="内. 大殿 - 日", location="大殿", time_of_day="日",
          elements=[Element(type="action", content="张三大步走进大殿")],
          characters_present=["n_01"]),
])


class TestConvertChapter:
    def test_happy_path(self, sample_chapter: Chapter, sample_kg: KnowledgeGraph) -> None:
        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.return_value = _MOCK_SCENE_LIST
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            scenes = convert_chapter(sample_chapter, sample_kg, ["上下文"])
        assert len(scenes) == 1
        assert scenes[0].scene_id == "s_000"
        assert scenes[0].elements[0].source_ref is not None

    def test_empty_kg_and_rag_works(self, sample_chapter: Chapter) -> None:
        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.return_value = _MOCK_SCENE_LIST
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            scenes = convert_chapter(sample_chapter, KnowledgeGraph(), [])
            assert len(scenes) == 1

    def test_failure_returns_empty(self, sample_chapter: Chapter) -> None:
        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.side_effect = RuntimeError("fail")
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            scenes = convert_chapter(sample_chapter, KnowledgeGraph(), [])
            assert scenes == []
