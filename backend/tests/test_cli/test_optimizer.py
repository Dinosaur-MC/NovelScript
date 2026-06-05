"""Tests for cli.optimizer — cross-scene consistency check, Auto-Fix."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cli.models import Element, KnowledgeGraph, KnowledgeNode, Scene
from cli.optimizer import _parse_and_validate, _serialize_scenes, optimize


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def sample_scenes() -> list[Scene]:
    return [
        Scene(
            scene_id="s_001",
            heading="内. 大殿 - 日",
            location="大殿",
            time_of_day="日",
            elements=[
                Element(type="action", content="张三走进大殿。"),
                Element(type="dialogue", content="臣有本启奏！"),
            ],
            characters_present=["n_01"],
        ),
        Scene(
            scene_id="s_002",
            heading="外. 花园 - 夜",
            location="花园",
            time_of_day="夜",
            elements=[
                Element(type="action", content="李四在月下独酌。"),
            ],
            characters_present=["n_02"],
        ),
    ]


@pytest.fixture
def sample_kg() -> KnowledgeGraph:
    return KnowledgeGraph(
        nodes=[
            KnowledgeNode(id="n_01", name="张三", node_type="character",
                          properties={"traits": ["勇敢", "忠诚"]}),
            KnowledgeNode(id="n_02", name="李四", node_type="character",
                          properties={"traits": ["阴险"]}),
        ],
    )


# ===========================================================================
# optimize
# ===========================================================================

class TestOptimize:
    def test_empty_scenes_returns_empty(self) -> None:
        result = optimize([], KnowledgeGraph())
        assert result == []

    def test_happy_path_returns_optimized(self, sample_scenes: list[Scene], sample_kg: KnowledgeGraph) -> None:
        """Pro model returns valid JSON → optimized scenes returned."""
        optimized_json = json.dumps([
            {
                "scene_id": "s_001",
                "heading": "内. 大殿 - 日",
                "location": "大殿",
                "time_of_day": "日",
                "elements": [
                    {"type": "action", "content": "张三走进大殿。", "source_ref": None},
                    {"type": "dialogue", "content": "臣有本启奏！", "source_ref": None},
                ],
                "characters_present": ["n_01"],
            },
        ])

        with patch("cli.optimizer.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content = optimized_json
            mock_get.return_value = mock_llm

            result = optimize(sample_scenes, sample_kg)
            assert len(result) >= 1
            assert all(isinstance(s, Scene) for s in result)

    def test_all_retries_exhausted_returns_originals(self, sample_scenes: list[Scene]) -> None:
        with patch("cli.optimizer.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content.strip.return_value = "bad json {{{"
            mock_get.return_value = mock_llm

            result = optimize(sample_scenes, KnowledgeGraph())
            assert result == sample_scenes  # returns originals on failure


# ===========================================================================
# _serialize_scenes
# ===========================================================================

class TestSerializeScenes:
    def test_empty_list(self) -> None:
        assert _serialize_scenes([]) == "[]"

    def test_two_scenes(self, sample_scenes: list[Scene]) -> None:
        result = _serialize_scenes(sample_scenes)
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["scene_id"] == "s_001"
        assert data[1]["location"] == "花园"
        assert "elements" in data[0]
        assert len(data[0]["elements"]) == 2

    def test_elements_have_type_and_content(self, sample_scenes: list[Scene]) -> None:
        result = _serialize_scenes(sample_scenes)
        data = json.loads(result)
        el = data[0]["elements"][0]
        assert "type" in el
        assert "content" in el


# ===========================================================================
# _parse_and_validate
# ===========================================================================

class TestParseValidate:
    def test_valid_array(self) -> None:
        raw = json.dumps([
            {"scene_id": "s_001", "heading": "x", "location": "x",
             "time_of_day": "x", "elements": [], "characters_present": []},
        ])
        scenes = _parse_and_validate(raw)
        assert len(scenes) == 1
        assert scenes[0].scene_id == "s_001"

    def test_single_dict_wrapped(self) -> None:
        raw = json.dumps({
            "scene_id": "s_099", "heading": "x", "location": "x",
            "time_of_day": "x", "elements": [], "characters_present": [],
        })
        scenes = _parse_and_validate(raw)
        assert len(scenes) == 1
        assert scenes[0].scene_id == "s_099"

    def test_preserves_source_ref(self) -> None:
        raw = json.dumps([
            {"scene_id": "s_001", "heading": "x", "location": "x",
             "time_of_day": "x",
             "elements": [{"type": "action", "content": "hello",
                           "source_ref": {"chapter_id": "ch_01", "offset": [0, 5]}}],
             "characters_present": []},
        ])
        scenes = _parse_and_validate(raw)
        assert scenes[0].elements[0].source_ref == {"chapter_id": "ch_01", "offset": [0, 5]}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_and_validate("not json")
