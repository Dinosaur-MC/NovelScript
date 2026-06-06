import { create } from "zustand";

export type RightTab = "preview" | "graph" | "chat";

interface UIState {
  leftWidth: number;   // percentage 0-100
  centerWidth: number;
  rightWidth: number;
  activeTab: RightTab;

  setPanelWidths: (l: number, c: number, r: number) => void;
  setActiveTab: (tab: RightTab) => void;
}

function loadWidths(): { l: number; c: number; r: number } {
  if (typeof window === "undefined") return { l: 30, c: 40, r: 30 };
  const raw = localStorage.getItem("panelWidths");
  if (!raw) return { l: 30, c: 40, r: 30 };
  try {
    const [l, c, r] = JSON.parse(raw) as number[];
    if (l >= 15 && c >= 30 && r >= 15 && Math.abs(l + c + r - 100) < 0.5) {
      return { l, c, r };
    }
  } catch { /* ignore corrupt data */ }
  return { l: 30, c: 40, r: 30 };
}

const defaults = loadWidths();

export const useUIStore = create<UIState>((set) => ({
  leftWidth: defaults.l,
  centerWidth: defaults.c,
  rightWidth: defaults.r,
  activeTab: "preview",

  setPanelWidths: (l, c, r) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("panelWidths", JSON.stringify([l, c, r]));
    }
    set({ leftWidth: l, centerWidth: c, rightWidth: r });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
}));
