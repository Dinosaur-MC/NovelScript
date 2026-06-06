"""Tests for pipeline_executor — background execution with mock pipeline."""

from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

from app.core.db import _session_factory
from app.models.sql import Novel, Task
from app.services.progress import progress_manager


@pytest.fixture(autouse=True)
def _clean_progress():
    yield
    with progress_manager._lock:
        progress_manager._queues.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_novel(source_text: str = "第一章 测试\n这是一段测试文本。") -> uuid.UUID:
    nid = uuid.uuid4()
    with _session_factory() as s:
        novel = Novel(
            id=nid,
            title="Test Novel",
            source_text=source_text,
            word_count=len(source_text),
        )
        s.add(novel)
        s.commit()
    return nid


def _create_test_task(novel_id: uuid.UUID) -> uuid.UUID:
    tid = uuid.uuid4()
    with _session_factory() as s:
        task = Task(id=tid, novel_id=novel_id, status="pending", progress=0)
        s.add(task)
        s.commit()
    return tid


def _cleanup(novel_id: uuid.UUID, task_id: uuid.UUID) -> None:
    with _session_factory() as s:
        for mid, model in ((task_id, Task), (novel_id, Novel)):
            obj = s.get(model, mid)
            if obj:
                s.delete(obj)
        s.commit()


def _build_mock_script():
    from cli.models import (
        Character as ScriptCharacter,
        Element,
        KnowledgeEdge,
        KnowledgeGraph,
        KnowledgeNode,
        Scene,
        Script,
    )

    return Script(
        meta={"test": True},
        summary="测试摘要",
        characters=[
            ScriptCharacter(id="c1", name="主角", aliases=["Z"], properties={}),
        ],
        scenes=[
            Scene(
                scene_id="s_001",
                heading="内. 大殿 - 日",
                location="大殿",
                time_of_day="日",
                elements=[Element(type="action", content="主角走进大殿。")],
                characters_present=["c1"],
            ),
        ],
        knowledge_graph=KnowledgeGraph(
            nodes=[KnowledgeNode(id="c1", name="主角", node_type="character")],
            edges=[KnowledgeEdge(source_node_id="c1", target_node_id="c1", relation="self")],
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecutePipelineEmptySource:
    def test_empty_source_text_leaves_task_pending(self) -> None:
        nid = _create_test_novel(source_text="")
        tid = _create_test_task(nid)
        try:
            from app.services.pipeline_executor import execute_pipeline

            execute_pipeline(tid, nid)
            time.sleep(0.3)

            with _session_factory() as s:
                task = s.get(Task, tid)
                assert task is not None
                assert task.status == "pending"
                assert task.progress == 0
        finally:
            _cleanup(nid, tid)

    def test_none_source_text_leaves_task_pending(self) -> None:
        nid = uuid.uuid4()
        with _session_factory() as s:
            novel = Novel(id=nid, title="No Source", source_text=None)
            s.add(novel)
            s.commit()
        tid = _create_test_task(nid)
        try:
            from app.services.pipeline_executor import execute_pipeline

            execute_pipeline(tid, nid)
            time.sleep(0.3)

            with _session_factory() as s:
                task = s.get(Task, tid)
                assert task.status == "pending"
        finally:
            _cleanup(nid, tid)


class TestExecutePipelineSuccess:
    def test_pipeline_sets_completed_and_saves_outputs(self) -> None:
        nid = _create_test_novel()
        tid = _create_test_task(nid)
        mock_script = _build_mock_script()

        try:
            # Create queue BEFORE spawning thread so events accumulate
            q = progress_manager.create_queue(str(tid))

            with patch("app.services.pipeline_executor.run_from_text") as mock_run:
                async def _fake_run(*args, **kwargs):
                    cb = kwargs.get("progress_callback")
                    if cb:
                        cb(10, "chunking")
                        cb(50, "converting")
                        cb(100, "assembling")
                    return mock_script

                mock_run.side_effect = _fake_run

                from app.services.pipeline_executor import execute_pipeline

                execute_pipeline(tid, nid)
                time.sleep(0.5)

                with _session_factory() as s:
                    task = s.get(Task, tid)
                    assert task is not None
                    assert task.status == "completed"
                    assert task.progress == 100
                    assert task.summary == "测试摘要"
                    assert task.script_yaml is not None
                    assert "scenes" in str(task.script_yaml)
                    assert task.script_json is not None
                    assert len(task.script_json["scenes"]) == 1  # type: ignore[index]
                    assert task.characters_json is not None
                    assert len(task.characters_json) == 1  # type: ignore[arg-type]

                # Drain events from the pre-created queue
                events = []
                import queue as qmod

                while True:
                    try:
                        events.append(q.get_nowait())
                    except qmod.Empty:
                        break
                types = [e["type"] for e in events]
                assert "progress" in types
                assert "complete" in types
        finally:
            _cleanup(nid, tid)


class TestExecutePipelineFailure:
    def test_pipeline_exception_sets_failed(self) -> None:
        nid = _create_test_novel()
        tid = _create_test_task(nid)

        try:
            q = progress_manager.create_queue(str(tid))

            with patch("app.services.pipeline_executor.run_from_text") as mock_run:
                async def _fail(*args, **kwargs):
                    raise RuntimeError("模拟管线崩溃")

                mock_run.side_effect = _fail

                from app.services.pipeline_executor import execute_pipeline

                execute_pipeline(tid, nid)
                time.sleep(0.5)

                with _session_factory() as s:
                    task = s.get(Task, tid)
                    assert task.status == "failed"
                    assert task.error_message is not None
                    assert "模拟管线崩溃" in str(task.error_message)

                events = []
                import queue as qmod

                while True:
                    try:
                        events.append(q.get_nowait())
                    except qmod.Empty:
                        break
                assert any(e["type"] == "error" for e in events)
        finally:
            _cleanup(nid, tid)
