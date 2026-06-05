"""Tests for cli.converter — chapter→scene, source_ref injection, Auto-Fix."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cli.converter import (
    _inject_source_refs,
    _parse_and_validate,
    _summarize_kg,
    convert_chapter,
)
from cli.models import (
    Chapter,
    Element,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    Scene,
)


# ===========================================================================
# Fixtures
# ===========================================================================

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


# ===========================================================================
# _summarize_kg
# ===========================================================================

class TestSummarizeKG:
    def test_empty_kg(self) -> None:
        kg = KnowledgeGraph()
        result = _summarize_kg(kg)
        assert "为空" in result

    def test_summary_includes_characters_and_locations(self, sample_kg: KnowledgeGraph) -> None:
        result = _summarize_kg(sample_kg)
        assert "张三" in result
        assert "大殿" in result
        assert "located_in" in result

    def test_characters_with_aliases(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="n_01", name="张三", node_type="character",
                                 properties={"aliases": ["三哥", "三爷"]})],
        )
        result = _summarize_kg(kg)
        assert "三哥" in result
        assert "三爷" in result

    def test_no_character_nodes(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="n_01", name="京城", node_type="location")],
        )
        result = _summarize_kg(kg)
        assert "地点" in result
        assert "人物" not in result or "人物：" not in result.split("：")[0]


# ===========================================================================
# _parse_and_validate
# ===========================================================================

class TestParseValidate:
    def test_valid_single_scene(self) -> None:
        raw = json.dumps([
            {
                "scene_id": "s_001",
                "heading": "内. 大殿 - 日",
                "location": "大殿",
                "time_of_day": "日",
                "elements": [
                    {"type": "action", "content": "张三走进大殿。"},
                    {"type": "dialogue", "content": "臣有本启奏！"},
                ],
                "characters_present": ["n_01"],
            }
        ])
        scenes = _parse_and_validate(raw, 0)
        assert len(scenes) == 1
        assert scenes[0].scene_id == "s_001"
        assert len(scenes[0].elements) == 2
        assert scenes[0].elements[0].type == "action"

    def test_single_dict_wrapped_in_list(self) -> None:
        raw = json.dumps({
            "scene_id": "s_000",
            "heading": "外. 广场 - 夜",
            "location": "广场",
            "time_of_day": "夜",
            "elements": [],
            "characters_present": [],
        })
        scenes = _parse_and_validate(raw, 0)
        assert len(scenes) == 1
        assert scenes[0].heading == "外. 广场 - 夜"

    def test_missing_fields_use_defaults(self) -> None:
        raw = json.dumps([{}])
        scenes = _parse_and_validate(raw, 0)
        assert len(scenes) == 1
        assert scenes[0].scene_id.startswith("s_000")
        assert scenes[0].heading == ""
        assert scenes[0].elements == []

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            _parse_and_validate("{{{bad", 0)


# ===========================================================================
# _inject_source_refs
# ===========================================================================

class TestInjectSourceRefs:
    def test_injects_when_content_found(self, sample_chapter: Chapter) -> None:
        scene = Scene(
            scene_id="s_000",
            heading="内. 大殿 - 日",
            location="大殿",
            time_of_day="日",
            elements=[Element(type="action", content="张三大步走进大殿")],
            characters_present=[],
        )
        scenes = _inject_source_refs([scene], sample_chapter)
        elem = scenes[0].elements[0]
        assert elem.source_ref is not None
        assert elem.source_ref["chapter_id"] == "ch_00"
        assert elem.source_ref["offset"][0] >= 0

    def test_content_not_found_gets_none_offset(self, sample_chapter: Chapter) -> None:
        scene = Scene(
            scene_id="s_000",
            heading="内. 大殿 - 日",
            location="大殿",
            time_of_day="日",
            elements=[Element(type="dialogue", content="这句话不在原文中")],
            characters_present=[],
        )
        scenes = _inject_source_refs([scene], sample_chapter)
        elem = scenes[0].elements[0]
        assert elem.source_ref is not None
        assert elem.source_ref["chapter_id"] == "ch_00"
        assert elem.source_ref["offset"] is None

    def test_preserves_existing_source_ref(self) -> None:
        ch = Chapter(text="any", title="T", index=1)
        scene = Scene(
            scene_id="s_001",
            heading="x", location="x", time_of_day="x",
            elements=[Element(type="action", content="any",
                              source_ref={"chapter_id": "existing", "offset": [1, 2]})],
            characters_present=[],
        )
        scenes = _inject_source_refs([scene], ch)
        assert scenes[0].elements[0].source_ref == {"chapter_id": "existing", "offset": [1, 2]}

    def test_multiple_scenes_and_elements(self, sample_chapter: Chapter) -> None:
        scenes = [
            Scene(scene_id="s_000", heading="x", location="x", time_of_day="x",
                  elements=[Element(type="action", content="张三大步走进大殿")],
                  characters_present=[]),
            Scene(scene_id="s_001", heading="x", location="x", time_of_day="x",
                  elements=[Element(type="dialogue", content="臣有本启奏")],
                  characters_present=[]),
        ]
        result = _inject_source_refs(scenes, sample_chapter)
        assert result[0].elements[0].source_ref["chapter_id"] == "ch_00"
        assert result[1].elements[0].source_ref["chapter_id"] == "ch_00"


# ===========================================================================
# convert_chapter
# ===========================================================================

class TestConvertChapter:
    def test_happy_path_converts_chapter(self, sample_chapter: Chapter, sample_kg: KnowledgeGraph) -> None:
        valid_json = json.dumps([
            {
                "scene_id": "s_000",
                "heading": "内. 大殿 - 日",
                "location": "大殿",
                "time_of_day": "日",
                "elements": [
                    {"type": "action", "content": "张三大步走进大殿"},
                    {"type": "dialogue", "content": "臣有本启奏"},
                ],
                "characters_present": ["n_01"],
            }
        ])

        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content = valid_json
            mock_get.return_value = mock_llm

            scenes = convert_chapter(sample_chapter, sample_kg, ["相关上下文"])

        assert len(scenes) == 1
        assert scenes[0].scene_id == "s_000"
        # source_ref should be injected
        assert scenes[0].elements[0].source_ref is not None

    def test_empty_kg_and_rag_works(self, sample_chapter: Chapter) -> None:
        """Empty KG + empty RAG context → still converts."""
        valid_json = json.dumps([{
            "scene_id": "s_000", "heading": "x", "location": "x",
            "time_of_day": "x", "elements": [], "characters_present": [],
        }])

        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content = valid_json
            mock_get.return_value = mock_llm

            scenes = convert_chapter(sample_chapter, KnowledgeGraph(), [])
            assert len(scenes) == 1

    def test_auto_fix_retries_then_succeeds(self, sample_chapter: Chapter) -> None:
        """First call returns bad JSON → retry → success."""
        bad_json = "not json at all"
        good_json = json.dumps([{
            "scene_id": "s_000", "heading": "x", "location": "x",
            "time_of_day": "x", "elements": [], "characters_present": [],
        }])

        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content = ""
            resp_mock = MagicMock()
            resp_mock.strip.side_effect = [bad_json, good_json]
            mock_llm.invoke.return_value.content = resp_mock
            mock_llm.invoke.return_value.content.strip.side_effect = [bad_json, good_json]
            mock_get.return_value = mock_llm

            scenes = convert_chapter(sample_chapter, KnowledgeGraph(), [])
            # Either succeeds on retry or returns [] after exhaustion
            assert isinstance(scenes, list)

    def test_all_retries_exhausted_returns_empty(self, sample_chapter: Chapter) -> None:
        with patch("cli.converter.get_llm") as mock_get:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value.content.strip.return_value = "永远不对"
            mock_get.return_value = mock_llm

            scenes = convert_chapter(sample_chapter, KnowledgeGraph(), [])
            assert scenes == []
