"""Tests for cli.pipeline — orchestrator, file loading, error handling."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.models import (
    Character,
    Element,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    Scene,
    Script,
)
from cli.pipeline import _programmatic_summary, main


# ===========================================================================
# _programmatic_summary — fallback when LLM is unavailable
# ===========================================================================

class TestProgrammaticSummary:
    def test_empty_kg(self) -> None:
        kg = KnowledgeGraph()
        result = _programmatic_summary(kg)
        assert "0 个" in result

    def test_with_characters_and_locations(self) -> None:
        kg = KnowledgeGraph(
            nodes=[
                KnowledgeNode(id="char_01", name="张三", node_type="character"),
                KnowledgeNode(id="char_02", name="李四", node_type="character"),
                KnowledgeNode(id="loc_01", name="京城", node_type="location"),
                KnowledgeNode(id="event_01", name="大战", node_type="event"),
            ],
        )
        result = _programmatic_summary(kg)
        assert "2 个主要角色" in result
        assert "1 个地点" in result
        assert "1 个关键事件" in result

    def test_many_characters_truncated(self) -> None:
        nodes = [KnowledgeNode(id=f"char_{i:02d}", name=f"角色{i}", node_type="character")
                 for i in range(10)]
        kg = KnowledgeGraph(nodes=nodes)
        result = _programmatic_summary(kg)
        assert "10 个主要角色" in result
        assert "..." in result  # truncated with ...

    def test_zero_locations_and_events_renders(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="char_01", name="张三", node_type="character")],
        )
        result = _programmatic_summary(kg)
        assert "0 个地点" in result
        assert "0 个关键事件" in result


# ===========================================================================
# pipeline.run — error handling
# ===========================================================================

class TestRunErrors:
    def test_file_not_found(self) -> None:
        from cli.pipeline import run
        import asyncio

        with pytest.raises(FileNotFoundError):
            asyncio.run(run("/nonexistent/file.txt"))


# ===========================================================================
# main — CLI entry point
# ===========================================================================

class TestMain:
    def test_no_args_prints_usage_and_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["cli.pipeline"]):
                main()
        assert exc_info.value.code == 2

    def test_file_not_found_prints_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["cli.pipeline", "/nonexistent_abc_xyz.txt"]):
                main()
        assert exc_info.value.code == 1
