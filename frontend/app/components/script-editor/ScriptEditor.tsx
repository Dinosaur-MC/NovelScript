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

      // Remeasure fonts after the web-font has loaded.
      // Monaco initialises synchronously, but web-fonts (Google Fonts)
      // arrive asynchronously — without this the cursor drifts on CJK lines.
      const monaco = (window as any).monaco;
      if (monaco?.editor?.remeasureFonts) {
        monaco.editor.remeasureFonts();
        // Second pass after a short delay catches late-arriving glyph tables
        setTimeout(() => monaco.editor.remeasureFonts(), 600);
      }
    },
    [editorHook],
  );

  // Re-measure fonts when the editor comes into view
  // (tab switch, panel resize, etc.)
  useEffect(() => {
    const timer = setTimeout(() => {
      const monaco = (window as any).monaco;
      monaco?.editor?.remeasureFonts?.();
    }, 300);
    return () => clearTimeout(timer);
  }, [initialYaml]);

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
      fontFamily: "'Sarasa Mono SC', '等距更纱黑体 SC', 'Sarasa Term SC', 'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Consolas', 'Noto Sans Mono CJK SC', 'Source Han Mono SC', monospace",
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
      automaticLayout: true,
    }),
    [],
  );

  return (
    <div className="ns-editor">
      {/* Validation error banner */}
      {validationErrors.length > 0 && (
        <div className="ns-editor-error">
          {validationErrors.join(" | ")}
        </div>
      )}

      {/* Toolbar */}
      <div className="ns-editor-toolbar">
        <div className="ns-editor-toolbar-actions">
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
          <span className="ns-editor-dirty">
            <span className="ns-editor-dirty-dot" />
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
            <div className="ns-editor-loading">
              加载编辑器中...
            </div>
          }
        />
      </div>
    </div>
  );
}
