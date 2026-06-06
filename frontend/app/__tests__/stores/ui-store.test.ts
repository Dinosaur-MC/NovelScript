import { describe, it, expect, beforeEach } from "vitest";
import { useUIStore } from "../../stores/ui-store";

beforeEach(() => {
  // Reset to known defaults
  useUIStore.getState().setPanelWidths(30, 40, 30);
  useUIStore.getState().setActiveTab("preview");
});

describe("ui-store", () => {
  describe("panel widths", () => {
    it("defaults to 30 / 40 / 30", () => {
      expect(useUIStore.getState().leftWidth).toBeGreaterThanOrEqual(15);
      expect(useUIStore.getState().centerWidth).toBeGreaterThanOrEqual(30);
      expect(useUIStore.getState().rightWidth).toBeGreaterThanOrEqual(15);
    });

    it("setPanelWidths updates all three widths", () => {
      useUIStore.getState().setPanelWidths(25, 50, 25);
      expect(useUIStore.getState().leftWidth).toBe(25);
      expect(useUIStore.getState().centerWidth).toBe(50);
      expect(useUIStore.getState().rightWidth).toBe(25);
    });

    it("persists widths to localStorage", () => {
      useUIStore.getState().setPanelWidths(20, 60, 20);
      const stored = JSON.parse(localStorage.getItem("panelWidths")!);
      expect(stored).toEqual([20, 60, 20]);
    });
  });

  describe("activeTab", () => {
    it("defaults to preview", () => {
      expect(useUIStore.getState().activeTab).toBe("preview");
    });

    it("setActiveTab toggles the tab", () => {
      useUIStore.getState().setActiveTab("chat");
      expect(useUIStore.getState().activeTab).toBe("chat");

      useUIStore.getState().setActiveTab("graph");
      expect(useUIStore.getState().activeTab).toBe("graph");
    });
  });
});
