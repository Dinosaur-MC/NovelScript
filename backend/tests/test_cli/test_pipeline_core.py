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
from cli.pipeline import _generate_summary, main


# ===========================================================================
# _generate_summary
# ===========================================================================

class TestGenerateSummary:
    def test_empty_scenes(self) -> None:
        kg = KnowledgeGraph()
        result = _generate_summary([], kg)
        assert "0 个场景" in result
        assert "0 个角色" in result

    def test_with_scenes_and_characters(self) -> None:
        kg = KnowledgeGraph(
            nodes=[
                KnowledgeNode(id="n_01", name="张三", node_type="character"),
                KnowledgeNode(id="n_02", name="李四", node_type="character"),
                KnowledgeNode(id="n_03", name="京城", node_type="location"),
            ],
        )
        scenes = [Scene(scene_id="s_001", heading="x", location="x", time_of_day="x")]
        result = _generate_summary(scenes, kg)
        assert "1 个场景" in result
        assert "2 个角色" in result
        assert "1 个地点" in result

    def test_many_characters_truncated(self) -> None:
        nodes = [KnowledgeNode(id=f"n_{i:02d}", name=f"角色{i}", node_type="character")
                 for i in range(10)]
        kg = KnowledgeGraph(nodes=nodes)
        result = _generate_summary([], kg)
        assert "10 个角色" in result
        assert "..." in result  # truncated with ...

    def test_no_locations(self) -> None:
        kg = KnowledgeGraph(
            nodes=[KnowledgeNode(id="n_01", name="张三", node_type="character")],
        )
        result = _generate_summary([], kg)
        assert "地点" not in result


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
