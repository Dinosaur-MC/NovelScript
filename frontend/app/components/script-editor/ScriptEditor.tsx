import { useCallback, useMemo, useRef } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useScriptStore } from "../../stores/script-store";
import { useEditorStore } from "../../stores/editor-store";
import { useKeyboard } from "../../hooks/useKeyboard";
import type { useAutoSave } from "../../hooks/useAutoSave";
import type { useScriptEditor } from "../../hooks/useScriptEditor";

interface Props {
  editorHook: ReturnType<typeof useScriptEditor>;
  autoSaveHook: ReturnType<typeof useAutoSave>;
}

export function ScriptEditor({ editorHook, autoSaveHook }: Props) {
  const yaml = useScriptStore((s) => s.yaml);
  const validationErrors = useEditorStore((s) => s.validationErrors);
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const dirty = useEditorStore((s) => s.dirty);
  const markDirty = useEditorStore((s) => s.markDirty);

  const latestValueRef = useRef(yaml ?? "");

  const handleMount: OnMount = useCallback(
    (ed: editor.IStandaloneCodeEditor) => {
      editorHook.bindEditor(ed);
    },
    [editorHook],
  );

  const handleChange = useCallback(
    (value: string | undefined) => {
      const v = value ?? "";
      latestValueRef.current = v;
      if (!dirty) markDirty(true);
      autoSaveHook.triggerSave(v);
    },
    [autoSaveHook, dirty, markDirty],
  );

  const handleSave = useCallback(() => {
    autoSaveHook.triggerSave(latestValueRef.current);
  }, [autoSaveHook]);

  useKeyboard({
    onSave: handleSave,
    onUndo: undo,
    onRedo: redo,
  });

  const options: editor.IStandaloneEditorConstructionOptions = useMemo(
    () => ({
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      lineNumbers: "on",
      minimap: { enabled: false },
      wordWrap: "on",
      wrappingIndent: "same",
      tabSize: 2,
      insertSpaces: true,
      scrollBeyondLastLine: false,
      renderWhitespace: "selection",
      bracketPairColorization: { enabled: true },
      guides: { indentation: true },
    }),
    [],
  );

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Validation error banner */}
      {validationErrors.length > 0 && (
        <div
          style={{
            padding: "6px 12px",
            backgroundColor: "var(--color-accent-danger)",
            color: "#fff",
            fontSize: 12,
            flexShrink: 0,
          }}
        >
          {validationErrors.join(" | ")}
        </div>
      )}

      {/* Editor */}
      <div style={{ flex: 1 }}>
        <Editor
          height="100%"
          defaultLanguage="yaml"
          value={yaml ?? ""}
          onChange={handleChange}
          onMount={handleMount}
          options={options}
          theme="vs-dark"
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
        />
      </div>
    </div>
  );
}
