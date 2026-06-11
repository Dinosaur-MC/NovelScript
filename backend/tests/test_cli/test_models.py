"""Tests for cli.models — Pydantic V2 validation of all pipeline data structures."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cli.models import (
    Chapter,
    Character,
    Element,
    Heading,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    Scene,
    Script,
    SourceRef,
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
# Element (backward-compat shim)
# ===========================================================================


class TestElement:
    def test_valid_element_with_source_ref(self) -> None:
        el = Element(
            type="dialogue",
            content="你好世界",
            source_ref=SourceRef(chapter_id="ch_00", offset=[0, 4], confidence="exact"),
        )
        assert el.type == "dialogue"
        assert el.source_ref.chapter_id == "ch_00"
        assert el.source_ref.confidence == "exact"

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
            heading=Heading(text="INT. Hall - DAY", location="Hall", time_of_day="DAY", int_ext="INT."),
            elements=[
                Element(type="action", content="Everyone stood."),
                Element(type="dialogue", content="I have a report."),
            ],
            characters_present=["char_01", "char_02"],
        )
        assert scene.scene_id == "s_001"
        assert len(scene.elements) == 2
        assert len(scene.characters_present) == 2
        assert scene.heading.location == "Hall"

    def test_defaults(self) -> None:
        scene = Scene(scene_id="s_000", heading=Heading(text="", location=""))
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
            description="勇敢的剑客",
            metadata={"age": 30, "role": "protagonist"},
        )
        assert c.id == "char_01"
        assert len(c.aliases) == 2
        assert c.description == "勇敢的剑客"


# ===========================================================================
# KnowledgeGraph
# ===========================================================================


class TestKnowledgeGraph:
    def test_kg_with_nodes_and_edges(self) -> None:
        nodes = [
            KnowledgeNode(id="char_01", label="张三", type="character", metadata={"traits": ["勇敢"]}),
            KnowledgeNode(id="loc_01", label="京城", type="location"),
        ]
        edges = [
            KnowledgeEdge(source="char_01", target="loc_01", relation="located_in", weight=0.9),
        ]
        kg = KnowledgeGraph(nodes=nodes, edges=edges)
        assert len(kg.nodes) == 2
        assert len(kg.edges) == 1
        assert kg.edges[0].weight == 0.9
        assert kg.nodes[0].label == "张三"

    def test_weight_range(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeEdge(source="a", target="b", relation="x", weight=1.5)

    def test_empty_kg(self) -> None:
        kg = KnowledgeGraph()
        assert kg.nodes == []
        assert kg.edges == []

    # Backward-compat construction (old field names via aliases)
    def test_old_name_construction(self) -> None:
        n = KnowledgeNode(id="char_01", name="张三", node_type="character", properties={"traits": ["勇敢"]})
        assert n.label == "张三"
        assert n.type == "character"
        assert n.metadata == {"traits": ["勇敢"]}

    def test_old_edge_construction(self) -> None:
        e = KnowledgeEdge(source_node_id="char_01", target_node_id="char_02", relation="knows")
        assert e.source == "char_01"
        assert e.target == "char_02"


# ===========================================================================
# Script
# ===========================================================================


class TestScript:
    def test_valid_script(self) -> None:
        script = Script(
            summary="这是一个测试剧本。",
            characters=[
                Character(id="char_01", name="测试角色", description="测试"),
            ],
            scenes=[
                Scene(
                    scene_id="s_001",
                    heading=Heading(text="INT. 测试场景 - DAY", location="测试场景", time_of_day="DAY"),
                    elements=[Element(type="action", content="测试动作。")],
                ),
            ],
            knowledge_graph=KnowledgeGraph(
                nodes=[KnowledgeNode(id="char_01", label="测试角色", type="character")],
            ),
        )
        assert script.title_page.title == ""
        assert len(script.scenes) == 1

    def test_defaults(self) -> None:
        script = Script()
        assert script.summary == ""
        assert script.characters == []
        assert script.scenes == []
        assert script.knowledge_graph.nodes == []

    def test_meta_backward_compat(self) -> None:
        script = Script(meta={"source_file": "test"})
        m = script.meta
        assert m["source_file"] == "test"
        # meta is a real dict field — supported alongside title_page + system_meta
