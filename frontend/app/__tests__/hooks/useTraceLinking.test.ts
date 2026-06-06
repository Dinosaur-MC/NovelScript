import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useTraceLinking } from "../../hooks/useTraceLinking";
import { useScriptStore } from "../../stores/script-store";
import { useNovelStore } from "../../stores/novel-store";

beforeEach(() => {
  useScriptStore.getState().clearScript();
  useNovelStore.getState().clearNovel();
});

describe("useTraceLinking", () => {
  function makeReader(scrollFn = vi.fn()) {
    return { bindEditor: vi.fn(), scrollToOffset: scrollFn };
  }
  function makeEditor(highlightFn = vi.fn()) {
    return {
      bindEditor: vi.fn(),
      getValue: vi.fn(() => ""),
      setValue: vi.fn(),
      applyExternalEdit: vi.fn(),
      highlightLines: highlightFn,
      clearHighlights: vi.fn(),
    };
  }

  describe("forward trace (element click → scroll source)", () => {
    it("calls scrollToOffset with the correct offset", () => {
      useScriptStore.getState().loadFromTaskResponse({
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              elements: [
                {
                  id: "el_alpha",
                  source_ref: {
                    chapter_id: "ch_02",
                    offset: [500, 550],
                    document_id: "d1",
                  },
                },
              ],
            },
          ],
        },
        characters_json: [],
      });

      const scrollToOffset = vi.fn();
      const { result } = renderHook(() =>
        useTraceLinking(makeReader(scrollToOffset), makeEditor()),
      );

      result.current.onElementClick("el_alpha", "s1", 0);
      expect(scrollToOffset).toHaveBeenCalledWith(500);
    });

    it("selects the right chapter before scrolling", () => {
      useNovelStore.getState().setChapters([
        { index: 1, title: "第一章", content: "..." },
        { index: 2, title: "第二章", content: "..." },
      ]);
      useScriptStore.getState().loadFromTaskResponse({
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              elements: [
                {
                  id: "el_x",
                  source_ref: {
                    chapter_id: "ch_02",
                    offset: [1200, 1350],
                    document_id: "d1",
                  },
                },
              ],
            },
          ],
        },
        characters_json: [],
      });

      const scrollToOffset = vi.fn();
      const { result } = renderHook(() =>
        useTraceLinking(makeReader(scrollToOffset), makeEditor()),
      );

      result.current.onElementClick("el_x", "s1", 0);
      expect(useNovelStore.getState().selectedChapterId).toBe("2");
      expect(scrollToOffset).toHaveBeenCalledWith(1200);
    });
  });

  it("does nothing on forward trace when element not in sourceRefMap", () => {
    const scrollToOffset = vi.fn();
    const { result } = renderHook(() =>
      useTraceLinking(makeReader(scrollToOffset), makeEditor()),
    );
    result.current.onElementClick("nonexistent_id", "s1", 0);
    expect(scrollToOffset).not.toHaveBeenCalled();
  });

  describe("backward trace (source select → highlight script)", () => {
    it("highlights elements whose source_ref overlaps the selection", () => {
      useScriptStore.getState().loadFromTaskResponse({
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              elements: [
                {
                  id: "el_1",
                  source_ref: {
                    chapter_id: "ch_01",
                    offset: [100, 200],
                    document_id: "d1",
                  },
                },
                {
                  id: "el_2",
                  source_ref: {
                    chapter_id: "ch_01",
                    offset: [150, 250],
                    document_id: "d1",
                  },
                },
                {
                  id: "el_3",
                  source_ref: {
                    chapter_id: "ch_02",
                    offset: [120, 180],
                    document_id: "d1",
                  },
                },
              ],
            },
          ],
        },
        characters_json: [],
      });

      const highlightLines = vi.fn();
      const { result } = renderHook(() =>
        useTraceLinking(makeReader(), makeEditor(highlightLines)),
      );

      result.current.onSourceSelect({
        chapterIndex: 1,
        startOffset: 120,
        endOffset: 180,
      });

      // el_1 [100,200] overlaps ch_01:[120,180] → line 2
      // el_2 [150,250] overlaps ch_01:[120,180] → line 2
      // el_3 is ch_02 — excluded
      expect(highlightLines).toHaveBeenCalledWith([2, 2]);
    });

    it("calls nothing when no elements match the selection", () => {
      const highlightLines = vi.fn();
      const { result } = renderHook(() =>
        useTraceLinking(makeReader(), makeEditor(highlightLines)),
      );

      result.current.onSourceSelect({
        chapterIndex: 99,
        startOffset: 0,
        endOffset: 100,
      });
      expect(highlightLines).not.toHaveBeenCalled();
    });
  });
});
