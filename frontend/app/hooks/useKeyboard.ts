import { useEffect } from "react";

interface Shortcuts {
  onSave?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
}

/**
 * Global keyboard shortcuts.
 * Ctrl+S → onSave
 * Ctrl+Z → onUndo
 * Ctrl+Y / Ctrl+Shift+Z → onRedo
 */
export function useKeyboard({ onSave, onUndo, onRedo }: Shortcuts) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const mod = e.ctrlKey || e.metaKey;

      if (mod && e.key === "s") {
        e.preventDefault();
        onSave?.();
      } else if (mod && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        onUndo?.();
      } else if (mod && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault();
        onRedo?.();
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onSave, onUndo, onRedo]);
}
