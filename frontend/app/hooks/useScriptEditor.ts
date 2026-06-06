import { useRef, useCallback } from "react";
import type { editor } from "monaco-editor";

/**
 * Command-style interface over a Monaco editor instance.
 * The component uses @monaco-editor/react; this hook exposes
 * getValue / setValue / highlightLines / applyExternalEdit.
 */
export function useScriptEditor() {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const decorationRef = useRef<string[]>([]);

  const bindEditor = useCallback((ed: editor.IStandaloneCodeEditor | null) => {
    editorRef.current = ed;
  }, []);

  const getValue = useCallback((): string => {
    return editorRef.current?.getModel()?.getValue() ?? "";
  }, []);

  const setValue = useCallback((value: string) => {
    editorRef.current?.getModel()?.setValue(value);
  }, []);

  /** Full-document replacement (used after AI patch / undo). */
  const applyExternalEdit = useCallback((newYaml: string) => {
    const ed = editorRef.current;
    if (!ed) return;
    const model = ed.getModel();
    if (!model) return;
    ed.pushUndoStop();
    model.pushEditOperations(
      [],
      [{ range: model.getFullModelRange(), text: newYaml }],
      () => null,
    );
    ed.pushUndoStop();
  }, []);

  /** Highlight specific line numbers with a sidebar marker. */
  const highlightLines = useCallback((lineNumbers: number[]) => {
    const ed = editorRef.current;
    if (!ed) return;
    const monaco = (window as unknown as Record<string, unknown>).monaco as typeof import("monaco-editor") | undefined;
    if (!monaco) return;

    decorationRef.current = ed.deltaDecorations(
      decorationRef.current,
      lineNumbers.map((ln) => ({
        range: new monaco.Range(ln, 1, ln, 1),
        options: {
          isWholeLine: true,
          linesDecorationsClassName: "monaco-source-marker",
        },
      })),
    );
  }, []);

  /** Clear all trace decorations. */
  const clearHighlights = useCallback(() => {
    const ed = editorRef.current;
    if (!ed) return;
    decorationRef.current = ed.deltaDecorations(decorationRef.current, []);
  }, []);

  /** Trigger Monaco's native undo. */
  const triggerUndo = useCallback(() => {
    editorRef.current?.trigger("keyboard", "undo", null);
  }, []);

  /** Trigger Monaco's native redo. */
  const triggerRedo = useCallback(() => {
    editorRef.current?.trigger("keyboard", "redo", null);
  }, []);

  /** Scroll to a line in the editor (1-based), positioning it near the top. */
  const revealLineNearTop = useCallback((line: number) => {
    const ed = editorRef.current;
    if (ed) ed.revealLineNearTop(line);
  }, []);

  /** Select a range of lines (1-based, inclusive). */
  const selectLines = useCallback((startLine: number, endLine: number) => {
    const ed = editorRef.current;
    if (!ed) return;
    const model = ed.getModel();
    if (!model) return;
    const m = (window as unknown as Record<string, unknown>).monaco as typeof import("monaco-editor") | undefined;
    if (!m) return;
    ed.setSelection(new m.Range(startLine, 1, endLine, model.getLineMaxColumn(endLine)));
  }, []);

  return { bindEditor, getValue, setValue, applyExternalEdit, highlightLines, clearHighlights, triggerUndo, triggerRedo, revealLineNearTop, selectLines };
}
