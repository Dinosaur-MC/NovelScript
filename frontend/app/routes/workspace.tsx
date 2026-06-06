import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router";
import { message, Tag } from "antd";

import { getTask } from "../api/tasks";
import { getNovel } from "../api/novels";
import { ApiError } from "../api/types";
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
  const rightW = useUIStore((s) => s.rightWidth);
  const setPanelWidths = useUIStore((s) => s.setPanelWidths);
  const readerCollapsed = useUIStore((s) => s.readerCollapsed);
  const setReaderCollapsed = useUIStore((s) => s.setReaderCollapsed);

  // Hooks — always called, safe with empty stores
  const autoSave = useAutoSave();
  const readerHook = useNovelReader();
  const editorHook = useScriptEditor();
  const traceHook = useTraceLinking(readerHook, editorHook);

  // Progress polling
  useSSE();

  // Async data load
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;

    async function load() {
      try {
        // Phase 1: Fetch task data (critical — must succeed)
        const taskData = await getTask(taskId!);
        if (cancelled) return;

        setTask(taskId!, taskData.novel_id, taskData.status as never, taskData.progress);
        loadScript({
          script_yaml: taskData.script_yaml,
          script_json: taskData.script_json,
          characters_json: taskData.characters_json,
        });

        // Phase 2: Fetch novel data (non-critical — editor can work without it)
        try {
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
        } catch (novelErr) {
          // Novel data unavailable — editor still works, just without source text
          if (!cancelled) {
            console.warn("Novel data unavailable:", novelErr);
            message.warning("小说原文加载失败，部分功能不可用");
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError && err.status === 404
          ? "任务不存在（可能已被删除）"
          : (err as Error).message || "加载失败，请检查网络后重试");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [taskId, setTask, loadScript, setNovel, setChapters]);

  if (error) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          backgroundColor: "var(--color-bg-canvas)",
        }}
      >
        <TaskBar loading={false} />
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
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
        <StatusBar />
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
      <TaskBar loading={loading} />
      <div style={{ flex: 1, overflow: "hidden" }}>
        {loading ? (
          <div
            style={{
              height: "100%",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 16,
            }}
          >
            <div className="ns-spinner" />
            <span style={{ color: "var(--color-text-secondary)", fontSize: 14 }}>
              加载中...
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
            {/* Collapse tab — instant appearance */}
            <div
              className="ns-reader-collapse-tab"
              onClick={() => setReaderCollapsed(false)}
              title="展开小说原文"
              style={{
                flexShrink: 0, overflow: "hidden",
                width: readerCollapsed ? 28 : 0,
                minWidth: readerCollapsed ? 28 : 0,
              }}
            >
              小说原文
            </div>
            {/* Reader panel — smooth collapse animation */}
            <div style={{
              flexShrink: 0, overflow: "hidden",
              width: readerCollapsed ? 0 : `${leftW}%`,
              minWidth: readerCollapsed ? 0 : 240,
              transition: "width 0.25s ease, min-width 0.25s ease",
            }}>
              <NovelReader readerHook={readerHook} traceHook={traceHook} />
            </div>
            {/* Splitter handle — always present for resizing */}
            <div
              onMouseDown={(e) => {
                e.preventDefault();
                const startX = e.clientX;
                const startW = leftW;
                const onMove = (ev: MouseEvent) => {
                  const container = (e.target as HTMLElement).parentElement;
                  if (!container) return;
                  const total = container.getBoundingClientRect().width;
                  const delta = ev.clientX - startX;
                  const newPct = Math.max(15, Math.min(70, startW + (delta / total) * 100));
                  const rem = 100 - newPct;
                  const innerRatio = centerW / (centerW + rightW || 1);
                  setPanelWidths(newPct, innerRatio * rem, rem - innerRatio * rem);
                };
                const onUp = () => {
                  document.removeEventListener("mousemove", onMove);
                  document.removeEventListener("mouseup", onUp);
                  document.body.style.cursor = "";
                  document.body.style.userSelect = "";
                };
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
                document.addEventListener("mousemove", onMove);
                document.addEventListener("mouseup", onUp);
              }}
              style={{
                width: 4, flexShrink: 0, cursor: "col-resize",
                backgroundColor: "var(--color-border-subtle)",
                transition: "background-color 0.15s",
              }}
              onMouseEnter={(el) => { (el.target as HTMLElement).style.backgroundColor = "var(--color-accent-primary)"; }}
              onMouseLeave={(el) => { (el.target as HTMLElement).style.backgroundColor = "var(--color-border-subtle)"; }}
            />
            {/* Editor + RightPanel */}
            <div style={{ flex: 1, overflow: "hidden", minWidth: 0 }}>
              <Splitter
                direction="horizontal"
                initialLeftPercent={centerW / (centerW + rightW || 1) * 100}
                minLeftPx={360}
                minRightPx={280}
                onResize={(pct) => {
                  const rem = 100 - (readerCollapsed ? 0 : leftW);
                  setPanelWidths(readerCollapsed ? 0 : leftW, (pct / 100) * rem, rem - (pct / 100) * rem);
                }}
              >
                <ScriptEditor editorHook={editorHook} autoSaveHook={autoSave} />
                <RightPanel traceHook={traceHook} editorHook={editorHook} />
              </Splitter>
            </div>
          </div>
        )}
      </div>
      <StatusBar />
    </div>
  );
}
