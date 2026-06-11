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
    Heading,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    Scene,
    Script,
    SourceRef,
    TitlePage,
)


@pytest.fixture
def sample_script() -> Script:
    """A small valid Script for exporter tests."""
    return Script(
        title_page=TitlePage(title="Test Script"),
        summary="A test script.",
        characters=[
            Character(id="char_01", name="Zhang San", aliases=["San Ge"], description="Protagonist", metadata={"role": "protagonist"}),
        ],
        scenes=[
            Scene(
                scene_id="s_001",
                heading=Heading(text="INT. Hall - DAY", location="Hall", time_of_day="DAY"),
                elements=[
                    Element(
                        type="action",
                        content="Zhang San enters the hall.",
                        source_ref=SourceRef(chapter_id="ch_00", offset=[0, 7]),
                    ),
                    Element(type="dialogue", content="I have a report."),
                ],
                characters_present=["char_01"],
            ),
        ],
        knowledge_graph=KnowledgeGraph(
            nodes=[KnowledgeNode(id="char_01", label="Zhang San", type="character")],
            edges=[],
        ),
    )


@pytest.fixture
def sample_novel_text() -> str:
    """A two-chapter sample novel for end-to-end testing."""
    return (
        "Chapter 1: Start\n"
        + "Zhang San strode into the hall, looking around.\n"
        + "He took a deep breath and said: 'I have a report!'\n"
        + "The emperor nodded: 'Granted.'\n"
        + "Chapter 2: Change\n"
        + "Outside the hall, the sky darkened. Thunder rumbled.\n"
        + "A guard rushed in: 'Report--!'\n"
    )


# ===========================================================================
# Exporter tests (no LLM needed)
# ===========================================================================


class TestExporter:
    def test_yaml_output_is_parseable(self, sample_script: Script) -> None:
        output = to_yaml(sample_script)
        parsed = yaml.safe_load(output)
        assert isinstance(parsed, dict)
        assert parsed["title_page"]["Title"] == "Test Script"
        assert len(parsed["scenes"]) == 1

    def test_json_output_is_parseable(self, sample_script: Script) -> None:
        output = to_json(sample_script)
        parsed = json.loads(output)
        assert parsed["title_page"]["title"] == "Test Script"

    def test_yaml_contains_source_ref(self, sample_script: Script) -> None:
        output = to_yaml(sample_script)
        assert "source_ref" in output
        assert "chapter_id" in output

    def test_json_roundtrip(self, sample_script: Script) -> None:
        """JSON export -> parse -> reconstruct should match."""
        output = to_json(sample_script)
        data = json.loads(output)
        reconstructed = Script(**data)
        assert reconstructed.summary == sample_script.summary
        assert len(reconstructed.scenes) == len(sample_script.scenes)


# ===========================================================================
# Chunker integration (no LLM needed for regex path)
# ===========================================================================


class TestChunkerIntegration:
    def test_e2e_sample_chunking(self, sample_novel_text: str) -> None:
        from cli.chunker import split_chapters

        chapters = split_chapters(sample_novel_text)
        assert len(chapters) == 2
        assert chapters[0].title == "Chapter 1: Start"

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
                    KnowledgeNode(id="char_01", label="Zhang San", type="character", metadata={"traits": ["brave"]}),
                    KnowledgeNode(id="char_02", label="Emperor", type="character"),
                    KnowledgeNode(id="loc_01", label="Hall", type="location"),
                ],
                edges=[
                    KnowledgeEdge(source="char_01", target="loc_01", relation="located_in"),
                ],
            )

            mock_scene = Scene(
                scene_id="s_000",
                heading=Heading(text="INT. Hall - DAY", location="Hall", time_of_day="DAY"),
                elements=[
                    Element(type="action", content="Zhang San enters the hall."),
                    Element(type="dialogue", content="I have a report!"),
                ],
                characters_present=["char_01", "char_02"],
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

            assert script.system_meta.source_word_count > 0
            assert len(script.characters) == 2
            assert len(script.scenes) == 1
            assert script.scenes[0].heading.location == "Hall"

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
        for key in ("title_page", "system_meta", "meta", "summary", "characters", "scenes", "knowledge_graph"):
            assert key in parsed, f"Missing top-level key: {key}"

    def test_knowledge_graph_section(self) -> None:
        script = Script(
            knowledge_graph=KnowledgeGraph(
                nodes=[KnowledgeNode(id="char_01", label="Test", type="character")],
                edges=[KnowledgeEdge(source="char_01", target="char_02", relation="knows")],
            ),
        )
        output = to_yaml(script)
        parsed = yaml.safe_load(output)
        assert len(parsed["knowledge_graph"]["nodes"]) == 1
        assert len(parsed["knowledge_graph"]["edges"]) == 1
