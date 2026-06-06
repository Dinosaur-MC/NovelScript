import { useCallback } from "react";
import { useScriptStore } from "../stores/script-store";
import { useNovelStore } from "../stores/novel-store";
import type { useNovelReader } from "./useNovelReader";
import type { useScriptEditor } from "./useScriptEditor";

export interface SourceSelectPayload {
  chapterIndex: number;
  startOffset: number;
  endOffset: number;
}

/**
 * Coordinates bidirectional trace linking between the three panels.
 * - Forward: click element → scroll source to offset
 * - Backward: select source text → highlight matching elements
 */
export function useTraceLinking(
  readerHook: ReturnType<typeof useNovelReader>,
  editorHook: ReturnType<typeof useScriptEditor>,
) {
  const sourceRefMap = useScriptStore((s) => s.sourceRefMap);
  const selectChapter = useNovelStore((s) => s.selectChapter);

  /** Forward trace: element click → scroll source to cited offset. */
  const onElementClick = useCallback(
    (elementId: string, _sceneId: string, _elementIdx: number) => {
      const ref = sourceRefMap.get(elementId);
      if (!ref) return;
      // Switch chapter if needed
      const chIdx = parseInt(ref.chapter_id.replace(/^ch_/, ""), 10);
      if (!isNaN(chIdx)) {
        selectChapter(chIdx);
      }
      readerHook.scrollToOffset(ref.offset[0]);
    },
    [sourceRefMap, selectChapter, readerHook],
  );

  /** Backward trace: source text selection → find and highlight matching elements. */
  const onSourceSelect = useCallback(
    ({ chapterIndex, startOffset, endOffset }: SourceSelectPayload) => {
      const chapterId = `ch_${String(chapterIndex).padStart(2, "0")}`;
      const matchingLines: number[] = [];

      // Iterate sourceRefMap to find elements whose offset overlaps
      for (const [, ref] of sourceRefMap) {
        if (
          ref.chapter_id === chapterId &&
          ref.offset[0] < endOffset &&
          ref.offset[1] > startOffset
        ) {
          matchingLines.push(ref.offset[0]);
        }
      }

      if (matchingLines.length > 0) {
        // Convert source offsets to approximate lines (100 chars per line heuristic)
        const lines = matchingLines.map((offset) => Math.floor(offset / 100) + 1);
        editorHook.highlightLines(lines);
      }
    },
    [sourceRefMap, editorHook],
  );

  return { onElementClick, onSourceSelect };
}
