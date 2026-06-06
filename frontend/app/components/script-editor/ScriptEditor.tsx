import { useCallback, useEffect, useMemo, useRef } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { Button } from "antd";
import { SaveOutlined, UndoOutlined, RedoOutlined } from "@ant-design/icons";
import { useScriptStore } from "../../stores/script-store";
import { useEditorStore } from "../../stores/editor-store";
import { useKeyboard } from "../../hooks/useKeyboard";
import type { useAutoSave } from "../../hooks/useAutoSave";
import type { useScriptEditor } from "../../hooks/useScriptEditor";

interface Props {
  editorHook: ReturnType<typeof useScriptEditor>;
  autoSaveHook: ReturnType<typeof useAutoSave>;
}

/** Template shown as placeholder / default content when the editor is empty. */
const YAML_TEMPLATE = `# ──────────────────────────────────────────────────────
# NovelScript 剧本 YAML 格式参考
# 保存时自动校验；编辑后右侧预览栏实时更新
# ──────────────────────────────────────────────────────

meta:
  source_file: ""
  chapter_count: 0
  scene_count: 0

summary: ""

characters:
  - id: ""
    name: ""
    aliases: []
    properties:
      traits: []

scenes:
  - scene_id: s_001
    heading: 地点 — 时间
    location: ""
    time_of_day: day
    characters_present: []
    elements:
      - type: action
        content: ""
        source_ref:
          chapter_id: ch_00
          offset: [0, 0]
      - type: dialogue
        content: ""
        character: ""
      - type: transition
        content: ""
`.trimStart();

export function ScriptEditor({ editorHook, autoSaveHook }: Props) {
  const initialYaml = useScriptStore((s) => s.yaml);
  const validationErrors = useEditorStore((s) => s.validationErrors);
  const dirty = useEditorStore((s) => s.dirty);

  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const latestValueRef = useRef(initialYaml ?? "");

  const updateYaml = useScriptStore((s) => s.updateYaml);

  // Parse initial yaml for preview on mount
  useEffect(() => {
    if (initialYaml) updateYaml(initialYaml);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMount: OnMount = useCallback(
    (ed: editor.IStandaloneCodeEditor) => {
      editorRef.current = ed;
      editorHook.bindEditor(ed);
    },
    [editorHook],
  );

  const handleChange = useCallback(
    (value: string | undefined) => {
      const v = value ?? "";
      latestValueRef.current = v;
      autoSaveHook.triggerSave(v);
      // Live preview: re-parse YAML → scenes for ScriptPreview + KnowledgeGraph
      updateYaml(v);
    },
    [autoSaveHook, updateYaml],
  );

  const handleSave = useCallback(() => {
    autoSaveHook.saveNow(latestValueRef.current);
  }, [autoSaveHook]);

  useKeyboard({
    onSave: handleSave,
    onUndo: editorHook.triggerUndo,
    onRedo: editorHook.triggerRedo,
  });

  const options: editor.IStandaloneEditorConstructionOptions = useMemo(
    () => ({
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace",
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

      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "4px 8px",
          borderBottom: "1px solid var(--color-border-subtle)",
          backgroundColor: "var(--color-bg-surface)",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Button
            type="text"
            size="small"
            icon={<SaveOutlined />}
            onClick={handleSave}
          >
            保存
          </Button>
          <Button
            type="text"
            size="small"
            icon={<UndoOutlined />}
            onClick={() => editorHook.triggerUndo()}
          >
            撤销
          </Button>
          <Button
            type="text"
            size="small"
            icon={<RedoOutlined />}
            onClick={() => editorHook.triggerRedo()}
          >
            重做
          </Button>
        </div>
        {dirty && (
          <span style={{ fontSize: 11, color: "var(--color-text-muted)", display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{
              display: "inline-block", width: 9, height: 9, borderRadius: "50%",
              backgroundColor: "var(--color-accent-warning)",
              boxShadow: "0 0 6px var(--color-accent-warning)",
            }} />
            未保存
          </span>
        )}
      </div>

      {/* Editor */}
      <div style={{ flex: 1 }}>
        <Editor
          height="100%"
          defaultLanguage="yaml"
          defaultValue={initialYaml || YAML_TEMPLATE}
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
