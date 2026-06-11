/**
 * Legacy hook — delegates to the centralized SSEManager via useTaskSSE.
 *
 * Maintains the same API for backward compatibility.
 * New code should import useTaskSSE directly.
 */
import { useEffect, useRef } from "react";
import { useTaskStore } from "../stores/task-store";
import { sseManager } from "../lib/sse-manager";

export function useSSE(onComplete?: (scriptId?: string) => void) {
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const updateProgress = useTaskStore((s) => s.updateProgress);
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const isActive = taskId && (status === "pending" || status === "preprocessing" || status === "converting");
    if (!isActive) return;

    // Subscribe to the shared SSEManager
    unsubRef.current = sseManager.subscribe(taskId, (event) => {
      if (event.status) {
        updateProgress(event.progress ?? 0, event.status as never, event.stage);
      }
      if (event.status === "completed") {
        onComplete?.(event.script_id);
      }
      if (event.error) {
        useTaskStore.getState().setError(event.error);
      }
    });

    return () => {
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }
    };
  }, [taskId, status, updateProgress, onComplete]);
}
