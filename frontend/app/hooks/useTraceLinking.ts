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
  const yaml = useScriptStore((s) => s.yaml);
  const selectChapter = useNovelStore((s) => s.selectChapter);

  /** Forward trace: element click → scroll source + editor to relevant position. */
  const onElementClick = useCallback(
    (elementId: string, sceneId: string, elementIdx: number) => {
      // Try primary id first, then positional fallback (sceneId_index)
      let ref = sourceRefMap.get(elementId);
      if (!ref) {
        ref = sourceRefMap.get(`${sceneId}_${elementIdx}`);
      }
      if (!ref) return;
      // Switch chapter if needed → reader scrolls to source offset
      const chIdx = parseInt(ref.chapter_id.replace(/^ch_/, ""), 10);
      if (!isNaN(chIdx)) {
        selectChapter(chIdx);
      }
      requestAnimationFrame(() => {
        setTimeout(() => readerHook.scrollToOffset(ref.offset[0]), 50);
      });

      // Editor: find the exact element line within the scene
      if (yaml && sceneId) {
        const lines = yaml.split("\n");
        const sceneStart = lines.findIndex((l) => l.includes(`scene_id: ${sceneId}`));
        if (sceneStart >= 0) {
          let inElements = false;
          let count = -1;
          let targetLine = sceneStart;
          let elementStartLine = -1;
          for (let i = sceneStart; i < lines.length; i++) {
            const line = lines[i];
            // Stop at next scene
            if (i > sceneStart && line.trimStart().startsWith("- scene_id:")) break;
            if (!inElements && line.trimStart().startsWith("elements:")) {
              inElements = true;
              continue;
            }
            if (inElements && line.trimStart().startsWith("- type:")) {
              count++;
              if (count === elementIdx) {
                elementStartLine = i;
                targetLine = i;
                break;
              }
            }
          }

          // Find the end of this element block (next "- type:" or end of elements)
          let elementEndLine = lines.length - 1;
          for (let i = elementStartLine + 1; i < lines.length; i++) {
            const line = lines[i];
            if (line.trimStart().startsWith("- type:") || line.trimStart().startsWith("- scene_id:")) {
              elementEndLine = i - 1;
              break;
            }
          }

          // Reveal target line in upper third
          setTimeout(() => {
            editorHook.revealLineNearTop(targetLine + 1);
            // Select the entire element block
            editorHook.selectLines(elementStartLine + 1, elementEndLine + 1);
          }, 100);
        }
      }
    },
    [sourceRefMap, selectChapter, readerHook, yaml, editorHook],
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
        // Deduplicate — same element may be registered under multiple keys
        const lines = [...new Set(matchingLines.map((offset) => Math.floor(offset / 100) + 1))];
        editorHook.highlightLines(lines);
      }
    },
    [sourceRefMap, editorHook],
  );

  return { onElementClick, onSourceSelect };
}
