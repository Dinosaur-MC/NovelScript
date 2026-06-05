import { useCallback } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { useScriptStore } from "../../stores/script-store";
import { useEditorStore } from "../../stores/editor-store";
import { useTaskStore } from "../../stores/task-store";
import { useKeyboard } from "../../hooks/useKeyboard";
import type { useScriptEditor } from "../../hooks/useScriptEditor";
import type { useAutoSave } from "../../hooks/useAutoSave";

interface Props {
  editorHook: ReturnType<typeof useScriptEditor>;
  autoSaveHook: ReturnType<typeof useAutoSave>;
}

export function ScriptEditor({ editorHook, autoSaveHook }: Props) {
  const yaml = useScriptStore((s) => s.yaml);
  const dirty = useEditorStore((s) => s.dirty);
  const markDirty = useEditorStore((s) => s.markDirty);
  const taskId = useTaskStore((s) => s.taskId);

  const handleMount: OnMount = useCallback(
    (ed, monaco) => {
      editorHook.bindEditor(ed);
      (window as unknown as Record<string, unknown>).monaco = monaco;
    },
    [editorHook],
  );

  const handleChange = useCallback(
    (_value: string | undefined) => {
      markDirty(true);
    },
    [markDirty],
  );

  const handleSave = useCallback(() => {
    const current = editorHook.getValue();
    autoSaveHook.triggerSave(current);
  }, [editorHook, autoSaveHook]);

  useKeyboard({ onSave: handleSave });

  if (!taskId) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-muted)",
          fontSize: 14,
        }}
      >
        请先选择任务
      </div>
    );
  }

  if (!yaml) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-muted)",
          fontSize: 14,
        }}
      >
        剧本生成中...
      </div>
    );
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Dirty indicator */}
      {dirty && (
        <div
          style={{
            height: 4,
            backgroundColor: "var(--color-accent-warning)",
            flexShrink: 0,
          }}
        />
      )}
      <div style={{ flex: 1 }}>
        <Editor
          height="100%"
          defaultLanguage="yaml"
          defaultValue={yaml}
          theme="vs-dark"
          onChange={handleChange}
          onMount={handleMount}
          loading={
            <div
              style={{
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--color-text-muted)",
              }}
            >
              加载编辑器中...
            </div>
          }
          options={{
            fontSize: 13,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            lineNumbers: "on",
            minimap: { enabled: false },
            wordWrap: "on",
            automaticLayout: true,
            scrollBeyondLastLine: false,
            renderWhitespace: "selection",
            tabSize: 2,
            folding: true,
            bracketPairColorization: { enabled: true },
            guides: { indentation: true },
          }}
        />
      </div>
    </div>
  );
}
