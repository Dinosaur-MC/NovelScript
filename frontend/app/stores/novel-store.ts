import { create } from "zustand";

export interface ChapterInfo {
  index: number;
  title: string;
  content: string;
}

interface NovelState {
  novelId: string | null;
  title: string;
  chapters: ChapterInfo[];
  selectedChapterId: string | null;

  setNovel: (id: string, title: string) => void;
  setChapters: (chapters: ChapterInfo[]) => void;
  selectChapter: (index: number) => void;
  clearNovel: () => void;
}

export const useNovelStore = create<NovelState>((set) => ({
  novelId: null,
  title: "",
  chapters: [],
  selectedChapterId: null,

  setNovel: (id, title) => set({ novelId: id, title }),

  setChapters: (chapters) =>
    set({
      chapters,
      selectedChapterId: chapters.length > 0 ? String(chapters[0].index) : null,
    }),

  selectChapter: (index) => set({ selectedChapterId: String(index) }),

  clearNovel: () =>
    set({ novelId: null, title: "", chapters: [], selectedChapterId: null }),
}));
