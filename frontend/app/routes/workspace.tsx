import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router";
import { Skeleton } from "antd";
import { getTask } from "../api/tasks";
import { getNovel } from "../api/novels";
import { useTaskStore } from "../stores/task-store";
import { useNovelStore } from "../stores/novel-store";
import { useScriptStore } from "../stores/script-store";
import { useUIStore } from "../stores/ui-store";
import { useAutoSave } from "../hooks/useAutoSave";
import { useSSE } from "../hooks/useSSE";
import { useNovelReader } from "../hooks/useNovelReader";
import { useScriptEditor } from "../hooks/useScriptEditor";
import { useTraceLinking } from "../hooks/useTraceLinking";
import { TaskBar } from "../components/task-bar/TaskBar";
import { StatusBar } from "../components/status-bar/StatusBar";
import { Splitter } from "../components/splitter/Splitter";
import { NovelReader } from "../components/novel-reader/NovelReader";
import { ScriptEditor } from "../components/script-editor/ScriptEditor";
import { RightPanel } from "../components/right-panel/RightPanel";
import type { Route } from "./+types/workspace";

export function meta({}: Route.MetaArgs) {
  return [{ title: "NovelScript — 剧本工作台" }];
}

export default function Workspace() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Stores
  const setTask = useTaskStore((s) => s.setTask);
  const setNovel = useNovelStore((s) => s.setNovel);
  const setChapters = useNovelStore((s) => s.setChapters);
  const loadScript = useScriptStore((s) => s.loadFromTaskResponse);
  const leftW = useUIStore((s) => s.leftWidth);
  const centerW = useUIStore((s) => s.centerWidth);

  // Hooks — always called, safe with empty stores
  const autoSave = useAutoSave();
  const readerHook = useNovelReader();
  const editorHook = useScriptEditor();
  const traceHook = useTraceLinking(readerHook, editorHook);

  // Progress polling
  useSSE();

  // Async data load — does NOT block initial render
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;

    async function load() {
      try {
        const taskData = await getTask(taskId!);
        if (cancelled) return;

        setTask(taskId!, taskData.novel_id, taskData.status as never, taskData.progress);
        loadScript({
          script_yaml: taskData.script_yaml,
          script_json: taskData.script_json,
          characters_json: taskData.characters_json,
        });

        const novelData = await getNovel(taskData.novel_id);
        if (cancelled) return;

        setNovel(novelData.novel.id, novelData.novel.title);
        setChapters(
          novelData.chapters.map((ch) => ({
            index: ch.chapter_index,
            title: ch.title ?? "",
            content: ch.content,
          })),
        );
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [taskId, setTask, loadScript, setNovel, setChapters]);

  // Only block render on fatal error, NOT on loading.
  // Each panel handles its own empty/loading state internally.
  if (error) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          backgroundColor: "var(--color-bg-canvas)",
        }}
      >
        <p style={{ color: "var(--color-accent-danger)", fontSize: 16 }}>{error}</p>
        <button
          onClick={() => navigate("/")}
          style={{
            padding: "8px 24px",
            background: "var(--color-accent-primary)",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          返回首页
        </button>
      </div>
    );
  }

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "var(--color-bg-canvas)",
      }}
    >
      <TaskBar />
      <div style={{ flex: 1, overflow: "hidden" }}>
        {loading ? (
          /* Skeleton shell while first load — layout visible immediately */
          <div style={{ height: "100%", display: "flex", gap: 4, padding: 4 }}>
            <div style={{ width: `${leftW}%`, padding: 16 }}>
              <Skeleton active paragraph={{ rows: 12 }} />
            </div>
            <div style={{ width: "4px", backgroundColor: "var(--color-border-subtle)" }} />
            <div style={{ flex: 1, display: "flex", gap: 4 }}>
              <div style={{ flex: 1, padding: 16 }}>
                <Skeleton active paragraph={{ rows: 20 }} />
              </div>
              <div style={{ width: "4px", backgroundColor: "var(--color-border-subtle)" }} />
              <div style={{ width: `${100 - leftW - (centerW / (centerW + (100 - leftW - centerW)) * 100)}%`, padding: 16 }}>
                <Skeleton active paragraph={{ rows: 8 }} />
              </div>
            </div>
          </div>
        ) : (
          <Splitter
            direction="horizontal"
            initialLeftPercent={leftW}
            minLeftPx={240}
            minRightPx={280 + 360}
          >
            <NovelReader readerHook={readerHook} traceHook={traceHook} />
            <Splitter
              direction="horizontal"
              initialLeftPercent={centerW / (centerW + (100 - leftW - centerW)) * 100}
              minLeftPx={360}
              minRightPx={280}
            >
              <ScriptEditor editorHook={editorHook} autoSaveHook={autoSave} />
              <RightPanel traceHook={traceHook} editorHook={editorHook} />
            </Splitter>
          </Splitter>
        )}
      </div>
      <StatusBar />
    </div>
  );
}
