import { useEffect, useRef } from "react";
import { useTaskStore } from "../stores/task-store";
import { getTaskStatus, createTaskStream } from "../api/tasks";

const POLL_INTERVAL_MS = 3000;
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Real-time SSE progress subscription with polling fallback.
 *
 * Prefers EventSource (`GET /api/v1/tasks/{task_id}/stream`) for
 * instant progress events. Falls back to 3-second polling if SSE
 * fails to connect or is not supported (Node.js test environments).
 *
 * @param onComplete - Optional callback invoked when pipeline completes,
 *   receiving the optional script_id from the complete event so callers
 *   (e.g. workspace) can navigate to the newly created Script.
 */
export function useSSE(onComplete?: (scriptId?: string) => void) {
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);
  const updateProgress = useTaskStore((s) => s.updateProgress);

  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    // Activate for all non-terminal statuses — "pending" is the initial state
    // right after task creation; "preprocessing"/"converting" are active stages.
    // The backend SSE endpoint handles all of them correctly, sending heartbeat
    // until the worker transitions to PROGRESS / SUCCESS.
    const isActive = taskId && (status === "pending" || status === "preprocessing" || status === "converting");
    if (!isActive) return;

    // Guard: already started for this taskId+status combination
    if (startedRef.current) return;
    startedRef.current = true;

    const failures = { count: 0 };

    function startPolling() {
      if (pollRef.current) return; // already polling

      pollRef.current = setInterval(async () => {
        try {
          const data = await getTaskStatus(taskId!);
          updateProgress(data.progress, data.status as never);
          failures.count = 0;
          if (data.status === "completed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            onComplete?.();
          }
          if (data.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch {
          failures.count++;
          if (failures.count >= MAX_CONSECUTIVE_FAILURES) {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      }, POLL_INTERVAL_MS);
    }

    // ── SSE primary path ──────────────────────────────────────────
    try {
      const es = createTaskStream(taskId);
      esRef.current = es;

      es.addEventListener("progress", (e: MessageEvent) => {
        failures.count = 0;
        try {
          const data = JSON.parse(e.data);
          const progress = data.progress ?? 0;
          const stage = data.stage as string | undefined;
          const status = data.status as string | undefined;
          updateProgress(progress, status as never, stage);
        } catch { /* malformed event — ignore */ }
      });

      es.addEventListener("complete", (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          updateProgress(data.progress ?? 100, "completed");
          onComplete?.(data.script_id as string | undefined);
        } catch {
          updateProgress(100, "completed");
          onComplete?.();
        }
        es.close();
        esRef.current = null;
      });

      es.addEventListener("error", (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          if (data.error) {
            console.error("SSE pipeline error:", data.error);
          }
        } catch { /* ignore parse errors */ }
        es.close();
        esRef.current = null;
      });

      es.onerror = () => {
        failures.count++;
        es.close();
        esRef.current = null;
        // EventSource onerror = network issue → fall back to polling
        startPolling();
      };
    } catch {
      // EventSource constructor threw (e.g. Node.js test env) → polling
      startPolling();
    }

    return () => {
      startedRef.current = false;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [taskId, status, updateProgress]);
}
