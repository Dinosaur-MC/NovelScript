import { useEffect, useRef } from "react";
import { useTaskStore } from "../stores/task-store";
import { getTaskStatus } from "../api/tasks";

const POLL_INTERVAL_MS = 2000;
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Polls GET /api/v1/tasks/{task_id}/status every 2s while the task is active.
 * Stops when task reaches 'completed' or 'failed', or after too many failures.
 * Switches to SSE when backend adds the stream endpoint (D3).
 */
export function useSSE() {
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const updateProgress = useTaskStore((s) => s.updateProgress);
  const failuresRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const isActive = taskId && (status === "preprocessing" || status === "converting");
    if (!isActive) return;

    timerRef.current = setInterval(async () => {
      try {
        const data = await getTaskStatus(taskId);
        updateProgress(data.progress, data.status as never);
        failuresRef.current = 0;
        if (data.status === "completed" || data.status === "failed") {
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } catch {
        failuresRef.current++;
        if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = null;
        }
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [taskId, status, updateProgress]);
}
