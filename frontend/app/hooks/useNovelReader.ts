import { useRef, useCallback } from "react";
import type { Editor } from "@tiptap/react";

/**
 * Command-style interface over a TipTap Editor instance.
 * The component owns the Editor; this hook exposes scroll/highlight
 * operations that useTraceLinking calls.
 */
export function useNovelReader() {
  const editorRef = useRef<Editor | null>(null);

  const bindEditor = useCallback((editor: Editor | null) => {
    editorRef.current = editor;
  }, []);

  /** Smooth-scroll TipTap to a character offset and apply temporary highlight. */
  const scrollToOffset = useCallback((offset: number) => {
    const editor = editorRef.current;
    if (!editor) return;

    // Resolve offset to a DOM position
    const pos = Math.min(offset + 1, editor.state.doc.content.size);
    const domAtPos = editor.view.domAtPos(pos);
    const node = domAtPos.node as HTMLElement | null;
    const el = node?.closest?.("p, h1, h2, h3, h4, h5, h6") ?? node;

    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      // Add highlight class for the fade animation
      el.classList.add("trace-highlight");
      setTimeout(() => el.classList.remove("trace-highlight"), 2200);
    }
  }, []);

  return { bindEditor, scrollToOffset };
}
