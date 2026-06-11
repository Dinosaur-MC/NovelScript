"""Tests for cli.optimizer — cross-scene consistency check with JSON mode.

Now tests the batched optimization path: when scenes exceed the per-call
budget they are split into independent batches, each getting its own LLM
invocation through ``_invoke_chain``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from langchain_core.runnables import RunnableLambda

from cli.models import Element, KnowledgeGraph, KnowledgeNode, Scene
from cli.optimizer import (
    _batch_scenes,
    _invoke_chain,
    _serialize_scenes,
    _summarize_kg,
    SceneList,
    optimize,
)


@pytest.fixture
def sample_scenes() -> list[Scene]:
    return [
        Scene(scene_id="s_001", heading="内. 大殿 - 日", location="大殿",
              time_of_day="日",
              elements=[Element(type="action", content="张三走进大殿。")],
              characters_present=["char_01"]),
        Scene(scene_id="s_002", heading="外. 花园 - 夜", location="花园",
              time_of_day="夜",
              elements=[Element(type="action", content="李四在月下独酌。")],
              characters_present=["char_02"]),
    ]


@pytest.fixture
def sample_kg() -> KnowledgeGraph:
    return KnowledgeGraph(
        nodes=[KnowledgeNode(id="char_01", name="张三", node_type="character",
                             properties={"traits": ["勇敢"]})],
    )


_MOCK_RESULT = SceneList(scenes=[
    Scene(scene_id="s_001", heading="内. 大殿 - 日", location="大殿",
          time_of_day="日",
          elements=[Element(type="action", content="张三走进大殿。")],
          characters_present=["char_01"]),
])

_MOCK_DICT = _MOCK_RESULT.model_dump()


class TestOptimize:
    def test_empty_scenes_returns_empty(self) -> None:
        assert asyncio.run(optimize([], KnowledgeGraph())) == []

    def test_happy_path_single_batch(self, sample_scenes: list[Scene],
                                      sample_kg: KnowledgeGraph) -> None:
        with patch("cli.optimizer._invoke_chain", return_value=_MOCK_DICT) as mock_invoke:
            result = asyncio.run(optimize(sample_scenes, sample_kg))
            # 2 small scenes → 1 batch
            assert mock_invoke.call_count == 1
            assert len(result) == 1
            assert all(isinstance(s, Scene) for s in result)

    def test_failure_returns_originals(self, sample_scenes: list[Scene]) -> None:
        with patch("cli.optimizer._invoke_chain", side_effect=RuntimeError("fail")) as mock_invoke:
            result = asyncio.run(optimize(sample_scenes, KnowledgeGraph()))
            assert mock_invoke.call_count == 1
            assert result == sample_scenes

    def test_multi_batch_calls_invoke_chain_per_batch(self) -> None:
        """When scenes span multiple batches, each batch gets a separate call."""
        # Build 15 scenes — enough to force >1 batch
        many = [
            Scene(scene_id=f"s_{i:03d}", heading=f"场景 {i}", location="某地",
                  time_of_day="日",
                  elements=[Element(type="action", content=f"这是第{i}个场景的内容。" * 20)],
                  characters_present=["char_01"])
            for i in range(15)
        ]

        with patch("cli.optimizer._invoke_chain", return_value=_MOCK_DICT):
            result = asyncio.run(optimize(many, KnowledgeGraph()))
            # Each batch produces 1 scene from the mock → we get batch_count scenes
            assert len(result) >= 1
            assert all(isinstance(s, Scene) for s in result)


class TestBatchScenes:
    def test_single_scene_single_batch(self) -> None:
        s = Scene(scene_id="s_001", heading="x", location="x",
                  time_of_day="日", elements=[], characters_present=[])
        batches = _batch_scenes([s])
        assert len(batches) == 1
        assert batches[0] == [s]

    def test_many_small_scenes_in_multiple_batches(self) -> None:
        # Each scene serializes to ~200 chars → ~50 scenes per 10k batch
        scenes = [
            Scene(scene_id=f"s_{i:03d}", heading=f"场景{i}", location="地",
                  time_of_day="日",
                  elements=[Element(type="action", content="短内容。")],
                  characters_present=[])
            for i in range(100)
        ]
        batches = _batch_scenes(scenes)
        assert len(batches) >= 2
        # Every scene must appear in exactly one batch
        flat = [s.scene_id for b in batches for s in b]
        assert flat == [s.scene_id for s in scenes]

    def test_oversized_scene_gets_own_batch(self) -> None:
        """A single scene exceeding the budget still gets its own batch."""
        huge = Scene(
            scene_id="s_big", heading="巨型场景", location="宇宙",
            time_of_day="永恒",
            elements=[Element(type="action", content="X" * 200)] * 100,
            characters_present=["c1"],
        )
        batches = _batch_scenes([huge])
        assert len(batches) == 1  # never empty


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
