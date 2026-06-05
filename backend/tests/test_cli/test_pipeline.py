"""Integration tests for the pipeline — end-to-end and YAML output validation.

These tests use a small in-memory sample that exercises the regex splitter
without requiring LLM API keys.  Modules that depend on LLM calls are
patched to return mock data.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cli.exporter import to_json, to_yaml
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
# Fixtures
# ===========================================================================


@pytest.fixture
def sample_script() -> Script:
    """A small valid Script for exporter tests."""
    return Script(
        meta={"title": "测试剧本"},
        summary="一个测试剧本。",
        characters=[
            Character(id="char_01", name="张三", aliases=["三哥"], properties={"role": "protagonist"}),
        ],
        scenes=[
            Scene(
                scene_id="s_001",
                heading="内. 大殿 - 日",
                location="大殿",
                time_of_day="日",
                elements=[
                    Element(
                        type="action",
                        content="张三走进大殿。",
                        source_ref={"chapter_id": "ch_00", "offset": [0, 7]},
                    ),
                    Element(type="dialogue", content="臣有本启奏。"),
                ],
                characters_present=["char_01"],
            ),
        ],
        knowledge_graph=KnowledgeGraph(
            nodes=[KnowledgeNode(id="n_01", name="张三", node_type="character")],
            edges=[],
        ),
    )


@pytest.fixture
def sample_novel_text() -> str:
    """A two-chapter sample novel for end-to-end testing."""
    return (
        "第一章 序章\n"
        + "张三大步走进大殿，环顾四周。百官肃立，气氛凝重。\n"
        + "他深吸一口气，朗声道：「臣有本启奏！」\n"
        + "皇帝微微颔首：「准奏。」\n"
        + "第二章 变故\n"
        + "大殿之外，天色骤变。乌云压顶，雷声隐隐。\n"
        + "一名侍卫匆匆跑入：「报——！」\n"
    )


# ===========================================================================
# Exporter tests (no LLM needed)
# ===========================================================================


class TestExporter:
    def test_yaml_output_is_parseable(self, sample_script: Script) -> None:
        output = to_yaml(sample_script)
        # Must be valid YAML
        parsed = yaml.safe_load(output)
        assert isinstance(parsed, dict)
        assert parsed["meta"]["title"] == "测试剧本"
        assert len(parsed["scenes"]) == 1

    def test_json_output_is_parseable(self, sample_script: Script) -> None:
        output = to_json(sample_script)
        parsed = json.loads(output)
        assert parsed["meta"]["title"] == "测试剧本"

    def test_yaml_contains_source_ref(self, sample_script: Script) -> None:
        output = to_yaml(sample_script)
        assert "source_ref" in output
        assert "chapter_id" in output

    def test_json_roundtrip(self, sample_script: Script) -> None:
        """JSON export → parse → reconstruct should match."""
        output = to_json(sample_script)
        data = json.loads(output)
        reconstructed = Script(**data)
        assert reconstructed.meta == sample_script.meta
        assert len(reconstructed.scenes) == len(sample_script.scenes)


# ===========================================================================
# Chunker integration (no LLM needed for regex path)
# ===========================================================================


class TestChunkerIntegration:
    def test_e2e_sample_chunking(self, sample_novel_text: str) -> None:
        from cli.chunker import split_chapters

        chapters = split_chapters(sample_novel_text)
        assert len(chapters) == 2
        assert chapters[0].title == "第一章 序章"
        assert chapters[1].title == "第二章 变故"
        assert "张三大步走进大殿" in chapters[0].text
        assert "天色骤变" in chapters[1].text

    def test_e2e_on_sample_file(self, sample_novel_text: str) -> None:
        """Write the sample to a temp file and run the full pipeline.

        LLM-dependent stages are mocked so the test passes without API keys.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as f:
            f.write(sample_novel_text)
            tmp_path = f.name

        try:
            mock_kg = KnowledgeGraph(
                nodes=[
                    KnowledgeNode(id="n_01", name="张三", node_type="character", properties={"traits": ["勇敢"]}),
                    KnowledgeNode(id="n_02", name="皇帝", node_type="character"),
                    KnowledgeNode(id="n_03", name="大殿", node_type="location"),
                ],
                edges=[
                    KnowledgeEdge(source_node_id="n_01", target_node_id="n_03", relation="located_in"),
                ],
            )

            mock_scene = Scene(
                scene_id="s_000",
                heading="内. 大殿 - 日",
                location="大殿",
                time_of_day="日",
                elements=[
                    Element(type="action", content="张三走进大殿。"),
                    Element(type="dialogue", content="臣有本启奏！"),
                ],
                characters_present=["n_01", "n_02"],
            )

            with (
                patch("cli.pipeline.extract_graph", return_value=mock_kg),
                patch("cli.pipeline.build_index", return_value=None),
                patch("cli.pipeline.search", return_value=[]),
                patch("cli.pipeline.convert_chapter", return_value=[mock_scene]),
                patch("cli.pipeline.optimize", return_value=[mock_scene]),
            ):
                from cli.pipeline import run
                import asyncio

                script = asyncio.run(run(tmp_path))

            assert script.meta["chapter_count"] == 2
            assert script.meta["scene_count"] == 1
            assert len(script.characters) == 2  # from KG
            assert len(script.scenes) == 1
            assert script.scenes[0].heading == "内. 大殿 - 日"

        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ===========================================================================
# YAML output structure validation
# ===========================================================================


class TestYAMLStructure:
    def test_yaml_has_required_top_level_keys(self) -> None:
        script = Script()
        output = to_yaml(script)
        parsed = yaml.safe_load(output)
        for key in ("meta", "summary", "characters", "scenes", "knowledge_graph"):
            assert key in parsed, f"Missing top-level key: {key}"

    def test_knowledge_graph_section(self) -> None:
        script = Script(
            knowledge_graph=KnowledgeGraph(
                nodes=[KnowledgeNode(id="n_01", name="测试", node_type="character")],
                edges=[KnowledgeEdge(source_node_id="n_01", target_node_id="n_02", relation="knows")],
            ),
        )
        output = to_yaml(script)
        parsed = yaml.safe_load(output)
        assert len(parsed["knowledge_graph"]["nodes"]) == 1
        assert len(parsed["knowledge_graph"]["edges"]) == 1
