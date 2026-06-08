import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router";
import { message, Tag, Button } from "antd";
import { SyncOutlined, HomeOutlined } from "@ant-design/icons";

import { getNovel, getNovelKnowledgeGraph } from "../api/novels";
import { getScript } from "../api/scripts";
import { getTask } from "../api/tasks";
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
  const { scriptId } = useParams<{ scriptId: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Stores
  const setTask = useTaskStore((s) => s.setTask);
  const setNovel = useNovelStore((s) => s.setNovel);
  const setChapters = useNovelStore((s) => s.setChapters);
  const loadScript = useScriptStore((s) => s.loadScript);
  const scriptLoaded = useScriptStore((s) => s.scriptId) !== null;
  const setKnowledgeGraph = useScriptStore((s) => s.setKnowledgeGraph);
  const leftW = useUIStore((s) => s.leftWidth);
  const centerW = useUIStore((s) => s.centerWidth);
  const rightW = useUIStore((s) => s.rightWidth);
  const setPanelWidths = useUIStore((s) => s.setPanelWidths);
  const readerCollapsed = useUIStore((s) => s.readerCollapsed);
  const setReaderCollapsed = useUIStore((s) => s.setReaderCollapsed);

  // Hooks
  const autoSave = useAutoSave();
  const readerHook = useNovelReader();
  const editorHook = useScriptEditor();
  const traceHook = useTraceLinking(readerHook, editorHook);

  // On pipeline complete, navigate to the newly created Script
  const onTaskComplete = useCallback((scriptId?: string) => {
    if (scriptId) {
      navigate(`/workspace/${scriptId}`, { replace: true });
    }
  }, [navigate]);

  // Progress polling (SSE) — activates when task-store has a running task
  useSSE(onTaskComplete);

  // Async data load — Phase 1: Script or Task, Phase 2: Novel + KG
  useEffect(() => {
    if (!scriptId) return;
    let cancelled = false;

    async function load() {
      try {
        const workId = scriptId!;
        let novelId: string | null = null;

        // ── Phase 1: Resolve route param as Script or Task ────────────
        try {
          // Try as Script first (pipeline completed → Script exists)
          const scriptData = await getScript(workId);
          if (cancelled) return;

          loadScript(scriptData);
          novelId = scriptData.novel_id;
          setTask("", novelId ?? "", workId, "completed", 100);
        } catch {
          // Not a Script — try as Task (in-progress conversion)
          try {
            const taskData = await getTask(workId);
            if (cancelled) return;

            novelId = taskData.novel_id;

            // If task is already completed, redirect to its Script
            if (taskData.status === "completed" && taskData.script_id) {
              if (!cancelled) {
                navigate(`/workspace/${taskData.script_id}`, { replace: true });
              }
              return;
            }

            // Task still in progress — set up SSE tracking
            setTask(workId, novelId, null, taskData.status as never, taskData.progress);
          } catch (taskErr) {
            // Neither Script nor Task exists
            if (!cancelled) {
              if (taskErr instanceof ApiError && taskErr.status === 404) {
                setError("剧本或任务不存在（可能已被删除）");
              } else {
                setError(taskErr instanceof Error ? taskErr.message : "加载失败，请检查网络后重试");
              }
            }
            return;
          }
        }

        // ── Phase 2: Fetch novel data (non-critical) ─────────────────
        if (novelId) {
          try {
            const novelData = await getNovel(novelId);
            if (cancelled) return;

            setNovel(novelId, novelData.novel.title);
            setChapters(
              novelData.chapters.map((ch) => ({
                index: ch.chapter_index,
                title: ch.title ?? "",
                content: ch.content,
              })),
            );
          } catch {
            if (!cancelled) console.warn("Novel data unavailable");
          }

          try {
            const kgData = await getNovelKnowledgeGraph(novelId);
            if (!cancelled) setKnowledgeGraph({ nodes: kgData.nodes, edges: kgData.edges });
          } catch {
            if (!cancelled) console.warn("Knowledge graph unavailable");
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [scriptId, loadScript, setTask, setNovel, setChapters, setKnowledgeGraph, navigate]);

  if (error) {
    return (
      <div className="ns-workspace-error">
        <TaskBar loading={false} />
        <div className="ns-workspace-error-body">
          <p className="ns-workspace-error-text">{error}</p>
          <button onClick={() => navigate("/")} className="ns-workspace-error-btn">返回首页</button>
        </div>
        <StatusBar />
      </div>
    );
  }

  return (
    <div className="ns-workspace-wrap">
      <TaskBar loading={loading} />
      <div className="ns-workspace-body">
        {loading ? (
          <div className="ns-workspace-loading">
            <div className="ns-spinner" />
            <span className="ns-workspace-loading-text">加载中...</span>
          </div>
        ) : !scriptLoaded ? (
          <div className="ns-workspace-task-progress">
            <SyncOutlined spin style={{ fontSize: 48, color: "var(--color-accent-primary)" }} />
            <h3>剧本转换中</h3>
            <p className="ns-workspace-task-progress-desc">
              正在将小说转换为剧本，请稍候…完成后将自动加载到编辑器中。
            </p>
            <Button type="link" icon={<HomeOutlined />} onClick={() => navigate("/")}>
              返回首页
            </Button>
          </div>
        ) : (
          <div className="ns-workspace-panels">
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
            <div
              className="ns-workspace-reader-panel"
              style={{
                width: readerCollapsed ? 0 : `${leftW}%`,
                minWidth: readerCollapsed ? 0 : 240,
              }}
            >
              <NovelReader readerHook={readerHook} traceHook={traceHook} />
            </div>
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
              className="ns-workspace-resizer"
            />
            <div className="ns-workspace-editor-area">
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
