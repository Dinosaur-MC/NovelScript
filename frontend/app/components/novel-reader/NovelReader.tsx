import { useCallback, useMemo, useEffect } from "react";
import { Select } from "antd";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { useNovelStore } from "../../stores/novel-store";
import type { useNovelReader } from "../../hooks/useNovelReader";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props {
  readerHook: ReturnType<typeof useNovelReader>;
  traceHook: ReturnType<typeof useTraceLinking>;
}

/** Stable extensions array — prevents TipTap editor recreation on re-render. */
function useExtensions() {
  return useMemo(
    () => [
      StarterKit.configure({ bold: false, italic: false }),
      Placeholder.configure({ placeholder: "请上传小说..." }),
    ],
    [],
  );
}

export function NovelReader({ readerHook, traceHook }: Props) {
  const chapters = useNovelStore((s) => s.chapters);
  const selectedChapterId = useNovelStore((s) => s.selectedChapterId);
  const selectChapter = useNovelStore((s) => s.selectChapter);
  const extensions = useExtensions();

  const selectedChapter = useMemo(
    () => chapters.find((ch) => String(ch.index) === selectedChapterId) ?? null,
    [chapters, selectedChapterId],
  );

  const editor = useEditor({
    extensions,
    content: selectedChapter?.content ?? "",
    editable: false, // read-only reader
  });

  // Bind editor instance to the hook so useTraceLinking can scroll
  useEffect(() => {
    readerHook.bindEditor(editor);
  }, [editor, readerHook]);

  // Update TipTap content when chapter changes
  useEffect(() => {
    if (editor && selectedChapter) {
      editor.commands.setContent(selectedChapter.content);
    }
  }, [editor, selectedChapter]);

  const handleTextSelect = useCallback(() => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    if (from !== to) {
      const chapterIndex = parseInt(selectedChapterId ?? "0", 10);
      traceHook.onSourceSelect({ chapterIndex, startOffset: from, endOffset: to });
    }
  }, [editor, selectedChapterId, traceHook]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Chapter selector */}
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "1px solid var(--color-border-subtle)",
          flexShrink: 0,
        }}
      >
        <Select
          size="small"
          value={selectedChapterId ?? undefined}
          onChange={(val) => selectChapter(parseInt(val, 10))}
          options={chapters.map((ch) => ({
            value: String(ch.index),
            label: `第${ch.index}章 ${ch.title || ""}`,
          }))}
          style={{ width: "100%" }}
          placeholder="选择章节"
        />
      </div>

      {/* Content */}
      <div
        onMouseUp={handleTextSelect}
        style={{
          flex: 1,
          overflow: "auto",
          padding: "16px",
          fontFamily: "var(--font-serif)",
          fontSize: 15,
          lineHeight: 1.8,
          color: "var(--color-text-primary)",
        }}
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
