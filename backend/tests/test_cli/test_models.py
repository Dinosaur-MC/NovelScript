"""Tests for cli.models — Pydantic V2 validation of all pipeline data structures."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cli.models import (
    Chapter,
    Character,
    Element,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    Scene,
    Script,
)


# ===========================================================================
# Chapter
# ===========================================================================


class TestChapter:
    def test_valid_chapter(self) -> None:
        ch = Chapter(text="正文内容", title="第一章 序", index=0)
        assert ch.text == "正文内容"
        assert ch.title == "第一章 序"
        assert ch.index == 0

    def test_index_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Chapter(text="x", title="x", index=-1)

    def test_text_is_required(self) -> None:
        with pytest.raises(ValidationError):
            Chapter(title="x", index=0)  # type: ignore[arg-type]


# ===========================================================================
# Element
# ===========================================================================


class TestElement:
    def test_valid_element_with_source_ref(self) -> None:
        el = Element(
            type="dialogue",
            content="你好世界",
            source_ref={"chapter_id": "ch_00", "offset": [0, 4]},
        )
        assert el.type == "dialogue"
        assert el.source_ref["chapter_id"] == "ch_00"

    def test_source_ref_is_optional(self) -> None:
        el = Element(type="action", content="他走进了房间。")
        assert el.source_ref is None


# ===========================================================================
# Scene
# ===========================================================================


class TestScene:
    def test_valid_scene(self) -> None:
        scene = Scene(
            scene_id="s_001",
            heading="内. 大殿 - 日",
            location="大殿",
            time_of_day="日",
            elements=[
                Element(type="action", content="众人肃立。"),
                Element(type="dialogue", content="臣有本启奏。"),
            ],
            characters_present=["char_01", "char_02"],
        )
        assert scene.scene_id == "s_001"
        assert len(scene.elements) == 2
        assert len(scene.characters_present) == 2

    def test_defaults(self) -> None:
        scene = Scene(scene_id="s_000", heading="", location="", time_of_day="")
        assert scene.elements == []
        assert scene.characters_present == []


# ===========================================================================
# Character
# ===========================================================================


class TestCharacter:
    def test_valid_character(self) -> None:
        c = Character(
            id="char_01",
            name="张三",
            aliases=["三哥", "三爷"],
            properties={"age": 30, "role": "protagonist"},
        )
        assert c.id == "char_01"
        assert len(c.aliases) == 2


# ===========================================================================
# KnowledgeGraph
# ===========================================================================


class TestKnowledgeGraph:
    def test_kg_with_nodes_and_edges(self) -> None:
        nodes = [
            KnowledgeNode(id="n_01", name="张三", node_type="character", properties={"traits": ["勇敢"]}),
            KnowledgeNode(id="n_02", name="京城", node_type="location"),
        ]
        edges = [
            KnowledgeEdge(source_node_id="n_01", target_node_id="n_02", relation="located_in", weight=0.9),
        ]
        kg = KnowledgeGraph(nodes=nodes, edges=edges)
        assert len(kg.nodes) == 2
        assert len(kg.edges) == 1
        assert kg.edges[0].weight == 0.9

    def test_weight_range(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeEdge(source_node_id="a", target_node_id="b", relation="x", weight=1.5)

    def test_empty_kg(self) -> None:
        kg = KnowledgeGraph()
        assert kg.nodes == []
        assert kg.edges == []


# ===========================================================================
# Script
# ===========================================================================


class TestScript:
    def test_valid_script(self) -> None:
        script = Script(
            meta={"title": "测试"},
            summary="这是一个测试剧本。",
            characters=[
                Character(id="char_01", name="测试角色"),
            ],
            scenes=[
                Scene(
                    scene_id="s_001",
                    heading="内. 测试场景 - 日",
                    location="测试场景",
                    time_of_day="日",
                    elements=[Element(type="action", content="测试动作。")],
                ),
            ],
            knowledge_graph=KnowledgeGraph(
                nodes=[KnowledgeNode(id="n_01", name="测试角色", node_type="character")],
            ),
        )
        assert script.meta["title"] == "测试"
        assert len(script.scenes) == 1

    def test_defaults(self) -> None:
        script = Script()
        assert script.meta == {}
        assert script.summary == ""
        assert script.characters == []
        assert script.scenes == []
        assert script.knowledge_graph.nodes == []
