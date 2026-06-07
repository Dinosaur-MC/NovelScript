import { useRef, useCallback } from "react";
import type { Editor } from "@tiptap/react";

/**
 * Command-style interface over a TipTap Editor instance.
 * The component owns the Editor; this hook exposes scroll/highlight
 * operations that useTraceLinking calls.
 */
export function useNovelReader() {
  const editorRef = useRef<Editor | null>(null);
  const chapterContentRef = useRef<Record<number, string>>({});

  const bindEditor = useCallback((editor: Editor | null) => {
    editorRef.current = editor;
  }, []);

  /** Cache chapter raw text so we can resolve offsets later. */
  const setChapterContent = useCallback((index: number, content: string) => {
    chapterContentRef.current[index] = content;
  }, []);

  /**
   * Scroll to the DOM element that contains text near *offset* in the
   * original plain-text chapter content.  Because TipTap renders HTML
   * paragraphs, plain-text offsets no longer map 1:1 to ProseMirror
   * positions — we search the DOM by text content instead.
   */
  const scrollToOffset = useCallback(
    (offset: number, chapterIndex: number) => {
      const editor = editorRef.current;
      if (!editor) return;

      const raw = chapterContentRef.current[chapterIndex];
      if (!raw) {
        // Fallback: use the ProseMirror position (close enough for short docs)
        const pos = Math.min(offset + 1, editor.state.doc.content.size);
        const domAtPos = editor.view.domAtPos(pos);
        const node = domAtPos.node as HTMLElement | null;
        const el = node?.closest?.("p, h1, h2, h3, h4, h5, h6") ?? node;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("trace-highlight");
          setTimeout(() => el.classList.remove("trace-highlight"), 2200);
        }
        return;
      }

      // Extract a unique-ish text snippet around the offset
      const start = Math.max(0, offset - 5);
      const end = Math.min(raw.length, offset + 60);
      const snippet = raw.slice(start, end).replace(/\s+/g, " ").trim();

      if (!snippet) return;

      // Walk the rendered DOM to find a <p> whose text includes the snippet
      const root = editor.view.dom;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let textNode: Text | null = null;

      while (walker.nextNode()) {
        if (walker.currentNode.textContent?.includes(snippet.slice(0, 20))) {
          textNode = walker.currentNode as Text;
          break;
        }
      }

      if (textNode) {
        const el = (textNode.parentElement as HTMLElement)?.closest?.("p, h1, h2, h3, h4, h5, h6") ?? textNode.parentElement;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("trace-highlight");
          setTimeout(() => el.classList.remove("trace-highlight"), 2200);
        }
      } else {
        // Last-resort fallback
        const pos = Math.min(offset + 1, editor.state.doc.content.size);
        const domAtPos = editor.view.domAtPos(pos);
        const node = domAtPos.node as HTMLElement | null;
        const el = node?.closest?.("p") ?? node;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("trace-highlight");
          setTimeout(() => el.classList.remove("trace-highlight"), 2200);
        }
      }
    },
    [],
  );

  return { bindEditor, scrollToOffset, setChapterContent };
}
