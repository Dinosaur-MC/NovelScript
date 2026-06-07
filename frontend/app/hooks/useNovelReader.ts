import { useRef, useCallback } from "react";
import type { Editor } from "@tiptap/react";

/**
 * Command-style interface over a TipTap Editor instance.
 * The component owns the Editor; this hook exposes scroll/highlight
 * operations that useTraceLinking calls.
 */
export function useNovelReader() {
  const editorRef = useRef<Editor | null>(null);

  /**
   * Paragraph offset index: maps chapterIndex → {lineOffsets: [start, end][]}
   * Built from the raw text at the time chapter content is set, so that
   * `scrollToOffset` can look up which paragraph (by index) a given
   * character offset falls into — fully deterministic, no text matching.
   */
  const paraIndexRef = useRef<Record<number, Array<[number, number]>>>({});

  const bindEditor = useCallback((editor: Editor | null) => {
    editorRef.current = editor;
  }, []);

  /**
   * Cache the raw chapter text AND pre-compute the character-offset ranges
   * for every line.  Lines are split by `\n` (same as plainTextToHtml).
   */
  const setChapterContent = useCallback((index: number, content: string) => {
    if (!content) {
      paraIndexRef.current[index] = [];
      return;
    }
    const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalized.split("\n");
    const ranges: Array<[number, number]> = [];
    let pos = 0;
    for (const line of lines) {
      ranges.push([pos, pos + line.length]);
      pos += line.length + 1; // +1 for the \n separator
    }
    paraIndexRef.current[index] = ranges;
  }, []);

  /** Find which line index contains *offset*.  Binary search for speed. */
  function lineForOffset(ranges: Array<[number, number]>, offset: number): number {
    let lo = 0, hi = ranges.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const [s, e] = ranges[mid];
      if (offset >= s && offset < e) return mid;
      if (offset < s) hi = mid - 1;
      else lo = mid + 1;
    }
    return lo > 0 ? Math.min(lo, ranges.length - 1) : 0;
  }

  /**
   * Scroll to the paragraph that contains the source text at *offset*
   * in chapter *chapterIndex*.  Uses a pre-computed line-offset index
   * so there is zero dependency on text-content fingerprint matching.
   *
   * Retries up to 3 times (120 ms each) to wait for TipTap to finish
   * rendering after a chapter switch.
   */
  const scrollToOffset = useCallback(
    (offset: number, chapterIndex: number) => {
      const editor = editorRef.current;
      if (!editor) return;

      const ranges = paraIndexRef.current[chapterIndex];
      const lineIdx = ranges ? lineForOffset(ranges, offset) : -1;

      function attempt(remaining: number) {
        const root = editorRef.current?.view?.dom;
        if (!root) {
          if (remaining > 0) setTimeout(() => attempt(remaining - 1), 120);
          return;
        }

        // Primary: find <p> by index (deterministic)
        if (lineIdx >= 0) {
          const paras = root.querySelectorAll("p");
          if (lineIdx < paras.length) {
            const el = paras[lineIdx] as HTMLElement;
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.classList.add("trace-highlight");
            setTimeout(() => el.classList.remove("trace-highlight"), 2200);
            return;
          }
        }

        // Fallback: ProseMirror position
        const ed = editorRef.current;
        if (ed) {
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
