import { describe, it, expect, beforeEach } from "vitest";
import { useNovelStore, type ChapterInfo } from "../../stores/novel-store";

beforeEach(() => {
  useNovelStore.getState().clearNovel();
});

const CHAPTERS: ChapterInfo[] = [
  { index: 1, title: "第一章", content: "Chapter 1 body" },
  { index: 2, title: "第二章", content: "Chapter 2 body" },
  { index: 3, title: "第三章", content: "Chapter 3 body" },
];

describe("novel-store", () => {
  it("setNovel stores id and title", () => {
    useNovelStore.getState().setNovel("novel-1", "星辰低语");
    expect(useNovelStore.getState().novelId).toBe("novel-1");
    expect(useNovelStore.getState().title).toBe("星辰低语");
  });

  it("setChapters auto-selects first chapter", () => {
    useNovelStore.getState().setChapters(CHAPTERS);
    expect(useNovelStore.getState().chapters).toHaveLength(3);
    expect(useNovelStore.getState().selectedChapterId).toBe("1");
  });

  it("setChapters with empty array clears selection", () => {
    useNovelStore.getState().setChapters([{ index: 1, title: "Only", content: "body" }]);
    expect(useNovelStore.getState().selectedChapterId).toBe("1");

    useNovelStore.getState().setChapters([]);
    expect(useNovelStore.getState().selectedChapterId).toBeNull();
  });

  it("selectChapter changes selectedChapterId", () => {
    useNovelStore.getState().setChapters(CHAPTERS);
    useNovelStore.getState().selectChapter(3);
    expect(useNovelStore.getState().selectedChapterId).toBe("3");
  });

  it("clearNovel resets all fields", () => {
    useNovelStore.getState().setNovel("n1", "Test");
    useNovelStore.getState().setChapters(CHAPTERS);
    useNovelStore.getState().clearNovel();
    expect(useNovelStore.getState().novelId).toBeNull();
    expect(useNovelStore.getState().title).toBe("");
    expect(useNovelStore.getState().chapters).toEqual([]);
    expect(useNovelStore.getState().selectedChapterId).toBeNull();
  });
});
