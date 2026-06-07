import { useCallback, useMemo, useEffect } from "react";
import { Button, Select } from "antd";
import { MenuFoldOutlined } from "@ant-design/icons";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { useNovelStore } from "../../stores/novel-store";
import { useUIStore } from "../../stores/ui-store";
import { ClientOnly } from "../ClientOnly";
import type { useNovelReader } from "../../hooks/useNovelReader";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props {
  readerHook: ReturnType<typeof useNovelReader>;
  traceHook: ReturnType<typeof useTraceLinking>;
}

/** Convert plain text to HTML paragraphs for TipTap rendering.
 *  Each non-empty line becomes its own <p>. */
function plainTextToHtml(text: string): string {
  if (!text) return "";
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return normalized
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return "";
      return `<p>${trimmed}</p>`;
    })
    .filter(Boolean)
    .join("");
}

/** Build a clean chapter label, avoiding duplicate "第X章" prefixes. */
function chapterLabel(index: number, title: string): string {
  const num = index + 1; // backend chapter_index is 0-based
  const cleaned = title.replace(/^第[0-9０-９零一二三四五六七八九十百千]+[章节回]\s*/, "").trim();
  if (cleaned) {
    return `第${num}章 ${cleaned}`;
  }
  return `第${num}章`;
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

function ReaderContent({ readerHook, traceHook }: Props) {
  const chapters = useNovelStore((s) => s.chapters);
  const selectedChapterId = useNovelStore((s) => s.selectedChapterId);
  const selectChapter = useNovelStore((s) => s.selectChapter);
  const extensions = useExtensions();

  const selectedChapter = useMemo(
    () => chapters.find((ch) => String(ch.index) === selectedChapterId) ?? null,
    [chapters, selectedChapterId],
  );

  // Convert plain text to HTML paragraphs so TipTap renders proper formatting
  const htmlContent = useMemo(
    () => plainTextToHtml(selectedChapter?.content ?? ""),
    [selectedChapter?.content],
  );

  const editor = useEditor({
    extensions,
    content: htmlContent,
    editable: false, // read-only reader
  });

  // Bind editor instance to the hook so useTraceLinking can scroll
  useEffect(() => {
    readerHook.bindEditor(editor);
  }, [editor, readerHook]);

  // Cache plain-text chapter content so useTraceLinking can resolve
  // source_ref offsets back to DOM positions for scroll-to-highlight
  useEffect(() => {
    for (const ch of chapters) {
      readerHook.setChapterContent(ch.index, ch.content);
    }
  }, [chapters, readerHook]);

  // Update TipTap content when chapter changes
  useEffect(() => {
    if (editor && selectedChapter) {
      editor.commands.setContent(htmlContent);
    }
  }, [editor, selectedChapter, htmlContent]);

  const handleTextSelect = useCallback(() => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    if (from !== to) {
      const chapterIndex = parseInt(selectedChapterId ?? "0", 10);
      traceHook.onSourceSelect({ chapterIndex, startOffset: from, endOffset: to });
    }
  }, [editor, selectedChapterId, traceHook]);

  return (
    <div className="ns-reader">
      {/* Chapter selector */}
      <div className="ns-reader-selector">
        <Select
          size="small"
          value={selectedChapterId ?? undefined}
          onChange={(val) => selectChapter(parseInt(val, 10))}
          options={chapters.map((ch) => ({
            value: String(ch.index),
            label: chapterLabel(ch.index, ch.title || ""),
          }))}
          style={{ flex: 1 }}
          placeholder="选择章节"
        />
        <Button
          type="text"
          size="small"
          icon={<MenuFoldOutlined />}
          onClick={() => useUIStore.getState().setReaderCollapsed(true)}
          title="折叠"
        />
      </div>

      {/* Content */}
      <div
        onMouseUp={handleTextSelect}
        className="ns-reader-content"
      >
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}

/** NovelReader shell — renders TipTap content only on the client
 *  to prevent SSR crashes from browser DOM API calls. */
export function NovelReader({ readerHook, traceHook }: Props) {
  return (
    <ClientOnly fallback={
      <div className="ns-reader">
        <div className="ns-reader-content" />
      </div>
    }>
      <ReaderContent readerHook={readerHook} traceHook={traceHook} />
    </ClientOnly>
  );
}
