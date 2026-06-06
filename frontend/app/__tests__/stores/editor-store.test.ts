import { describe, it, expect, beforeEach } from "vitest";
import { useEditorStore } from "../../stores/editor-store";

beforeEach(() => {
  useEditorStore.getState().clearHistory();
  useEditorStore.getState().markDirty(false);
  useEditorStore.getState().setValidationErrors([]);
});

const PATCH_A = { op: "replace", path: "/scenes/0/title", value: "New Title" };
const PATCH_B = { op: "add", path: "/scenes/1", value: {} };

describe("editor-store", () => {
  describe("pushUndo", () => {
    it("pushes patch onto undoStack and clears redoStack", () => {
      const s = useEditorStore.getState();
      expect(s.undoStack).toHaveLength(0);

      s.pushUndo(PATCH_A);
      // pushUndo also resets dirty
      expect(useEditorStore.getState().undoStack).toHaveLength(1);
      expect(useEditorStore.getState().undoStack[0]).toEqual(PATCH_A);
      expect(useEditorStore.getState().redoStack).toHaveLength(0);
      expect(useEditorStore.getState().dirty).toBe(false);
    });

    it("caps undoStack at 50 entries", () => {
      for (let i = 0; i < 55; i++) {
        useEditorStore.getState().pushUndo({
          op: "replace",
          path: `/scenes/${i}`,
          value: i,
        });
      }
      const stack = useEditorStore.getState().undoStack;
      expect(stack.length).toBe(50);
      // oldest entry shifted out — first kept is index 5
      expect((stack[0].value as number)).toBe(5);
      expect((stack[49].value as number)).toBe(54);
    });
  });

  describe("undo", () => {
    it("returns null when stack is empty", () => {
      expect(useEditorStore.getState().undo()).toBeNull();
    });

    it("pops undoStack, pushes redoStack, returns the patch", () => {
      useEditorStore.getState().pushUndo(PATCH_A);
      useEditorStore.getState().pushUndo(PATCH_B);

      const patch = useEditorStore.getState().undo();
      expect(patch).toEqual(PATCH_B);
      expect(useEditorStore.getState().undoStack).toHaveLength(1);
      expect(useEditorStore.getState().redoStack).toHaveLength(1);
      expect(useEditorStore.getState().redoStack[0]).toEqual(PATCH_B);
    });
  });

  describe("redo", () => {
    it("returns null when redoStack is empty", () => {
      expect(useEditorStore.getState().redo()).toBeNull();
    });

    it("pops redoStack, pushes undoStack, returns the patch", () => {
      useEditorStore.getState().pushUndo(PATCH_A);
      useEditorStore.getState().undo(); // A now on redoStack
      expect(useEditorStore.getState().redoStack).toHaveLength(1);

      const patch = useEditorStore.getState().redo();
      expect(patch).toEqual(PATCH_A);
      expect(useEditorStore.getState().redoStack).toHaveLength(0);
      expect(useEditorStore.getState().undoStack).toHaveLength(1);
    });
  });

  describe("markDirty / setValidationErrors / clearHistory", () => {
    it("markDirty toggles the dirty flag", () => {
      useEditorStore.getState().markDirty(true);
      expect(useEditorStore.getState().dirty).toBe(true);
      useEditorStore.getState().markDirty(false);
      expect(useEditorStore.getState().dirty).toBe(false);
    });

    it("setValidationErrors stores error strings", () => {
      useEditorStore.getState().setValidationErrors(["line 5: invalid YAML"]);
      expect(useEditorStore.getState().validationErrors).toEqual(["line 5: invalid YAML"]);
    });

    it("clearHistory empties both stacks", () => {
      useEditorStore.getState().pushUndo(PATCH_A);
      useEditorStore.getState().pushUndo(PATCH_B);
      useEditorStore.getState().undo();
      useEditorStore.getState().clearHistory();
      expect(useEditorStore.getState().undoStack).toHaveLength(0);
      expect(useEditorStore.getState().redoStack).toHaveLength(0);
    });
  });
});
