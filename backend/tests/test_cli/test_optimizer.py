"""Tests for cli.optimizer — cross-scene consistency check with LangChain."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cli.models import Element, KnowledgeGraph, KnowledgeNode, Scene
from cli.optimizer import _serialize_scenes, _summarize_kg, SceneList, optimize


@pytest.fixture
def sample_scenes() -> list[Scene]:
    return [
        Scene(scene_id="s_001", heading="内. 大殿 - 日", location="大殿",
              time_of_day="日",
              elements=[Element(type="action", content="张三走进大殿。")],
              characters_present=["n_01"]),
        Scene(scene_id="s_002", heading="外. 花园 - 夜", location="花园",
              time_of_day="夜",
              elements=[Element(type="action", content="李四在月下独酌。")],
              characters_present=["n_02"]),
    ]


@pytest.fixture
def sample_kg() -> KnowledgeGraph:
    return KnowledgeGraph(
        nodes=[KnowledgeNode(id="n_01", name="张三", node_type="character",
                             properties={"traits": ["勇敢"]})],
    )


_MOCK_RESULT = SceneList(scenes=[
    Scene(scene_id="s_001", heading="内. 大殿 - 日", location="大殿",
          time_of_day="日",
          elements=[Element(type="action", content="张三走进大殿。")],
          characters_present=["n_01"]),
])


class TestOptimize:
    def test_empty_scenes_returns_empty(self) -> None:
        assert optimize([], KnowledgeGraph()) == []

    def test_happy_path(self, sample_scenes: list[Scene], sample_kg: KnowledgeGraph) -> None:
        with patch("cli.optimizer.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.return_value = _MOCK_RESULT
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            result = optimize(sample_scenes, sample_kg)
            assert len(result) == 1
            assert all(isinstance(s, Scene) for s in result)

    def test_failure_returns_originals(self, sample_scenes: list[Scene]) -> None:
        with patch("cli.optimizer.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_structured = MagicMock()
            mock_structured.invoke.side_effect = RuntimeError("fail")
            mock_llm.with_structured_output.return_value = mock_structured
            mock_get.return_value = mock_llm
            result = optimize(sample_scenes, KnowledgeGraph())
            assert result == sample_scenes


class TestSerializeScenes:
    def test_empty_list(self) -> None:
        assert _serialize_scenes([]) == "[]"

    def test_two_scenes(self, sample_scenes: list[Scene]) -> None:
        result = _serialize_scenes(sample_scenes)
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["scene_id"] == "s_001"


class TestSummarizeKG:
    def test_with_characters(self, sample_kg: KnowledgeGraph) -> None:
        result = _summarize_kg(sample_kg)
        assert "张三" in result
        assert "勇敢" in result

    def test_empty_kg(self) -> None:
        assert _summarize_kg(KnowledgeGraph()) == ""
