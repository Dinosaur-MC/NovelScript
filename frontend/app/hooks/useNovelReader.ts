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
   * Search the DOM for a text node whose content (whitespace-collapsed)
   * includes *needle* (also collapsed), then scroll + highlight it.
   * Returns true on match, false otherwise.
   */
  function findAndScroll(root: HTMLElement | null, needle: string): boolean {
    if (!root || !needle) return false;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = (walker.currentNode.textContent ?? "").replace(/\s+/g, "");
      if (text.includes(needle)) {
        const el = (walker.currentNode.parentElement as HTMLElement)
          ?.closest?.("p, h1, h2, h3, h4, h5, h6")
          ?? walker.currentNode.parentElement;
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("trace-highlight");
          setTimeout(() => el.classList.remove("trace-highlight"), 2200);
        }
        return true;
      }
    }
    return false;
  }

  /**
   * Scroll to the DOM element that contains the text at *offset* in the
   * plain-text chapter.  Because TipTap renders HTML paragraphs, character
   * offsets don't map to ProseMirror positions, so we search by content.
   *
   * Supports retries: when the chapter was just switched, the DOM may not
   * be ready yet.
   */
  const scrollToOffset = useCallback(
    (offset: number, chapterIndex: number) => {
      const editor = editorRef.current;
      if (!editor) return;

      const raw = chapterContentRef.current[chapterIndex];

      // Build a stable fingerprint (max 15 chars, no whitespace) from
      // the raw text starting AT *offset* — stays within one paragraph.
      const fingerprint = raw
        ? raw.slice(offset, offset + 30).replace(/\s+/g, "").slice(0, 15)
        : "";

      function attempt(remaining: number) {
        const root = editorRef.current?.view?.dom ?? null;

        // Try fingerprint first
        if (fingerprint && findAndScroll(root as HTMLElement | null, fingerprint)) return;

        // Fallback: ProseMirror position
        if (editorRef.current) {
          const ed = editorRef.current;
          const pos = Math.min(offset + 1, ed.state.doc.content.size);
          const domAtPos = ed.view.domAtPos(pos);
          const node = domAtPos.node as HTMLElement | null;
          const el = node?.closest?.("p") ?? node;
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.classList.add("trace-highlight");
            setTimeout(() => el.classList.remove("trace-highlight"), 2200);
            return;
          }
        }

        // DOM not ready yet — retry (e.g. chapter switch in progress)
        if (remaining > 0) {
          setTimeout(() => attempt(remaining - 1), 120);
        }
      }

      attempt(3);
    },
    [],
  );

  return { bindEditor, scrollToOffset, setChapterContent };
}
