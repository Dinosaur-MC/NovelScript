import { create } from "zustand";

// PatchOp shape matches what api/editor.ts exports
interface PatchOp {
  op: string;
  path: string;
  value: unknown;
}

interface EditorState {
  undoStack: PatchOp[];
  redoStack: PatchOp[];
  dirty: boolean;
  validationErrors: string[];

  pushUndo: (patch: PatchOp) => void;
  undo: () => PatchOp | null;
  redo: () => PatchOp | null;
  markDirty: (d: boolean) => void;
  setValidationErrors: (errors: string[]) => void;
  clearHistory: () => void;
}

const MAX_UNDO = 50;

export const useEditorStore = create<EditorState>((set, get) => ({
  undoStack: [],
  redoStack: [],
  dirty: false,
  validationErrors: [],

  pushUndo: (patch) =>
    set((s) => {
      const stack = [...s.undoStack, patch];
      if (stack.length > MAX_UNDO) stack.shift();
      return { undoStack: stack, redoStack: [], dirty: false };
    }),

  undo: () => {
    const { undoStack } = get();
    if (undoStack.length === 0) return null;
    const patch = undoStack[undoStack.length - 1];
    set((s) => ({
      undoStack: s.undoStack.slice(0, -1),
      redoStack: [...s.redoStack, patch],
    }));
    return patch;
  },

  redo: () => {
    const { redoStack } = get();
    if (redoStack.length === 0) return null;
    const patch = redoStack[redoStack.length - 1];
    set((s) => ({
      redoStack: s.redoStack.slice(0, -1),
      undoStack: [...s.undoStack, patch],
    }));
    return patch;
  },

  markDirty: (d) => set({ dirty: d }),

  setValidationErrors: (errors) => set({ validationErrors: errors }),

  clearHistory: () => set({ undoStack: [], redoStack: [] }),
}));
