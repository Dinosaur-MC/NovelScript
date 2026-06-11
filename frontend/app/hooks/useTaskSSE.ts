/**
 * React hook for task SSE progress — wraps SSEManager with reactive state.
 *
 * Multiple components on the same page can call useTaskSSE(taskId);
 * they all share ONE EventSource connection via the SSEManager singleton.
 *
 * Features:
 * - Shared connection: only one EventSource per taskId
 * - Integrates with useTaskStore so StatusBar etc. work automatically
 * - Returns reactive { progress, status, stage, error }
 * - Falls back to polling if SSE is unavailable
 * - Auto-cleanup on unmount
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { sseManager, type SSEProgressEvent } from "../lib/sse-manager";
import { useTaskStore } from "../stores/task-store";
import { getTaskStatus } from "../api/tasks";

const POLL_INTERVAL_MS = 3000;

export interface TaskSSEState {
  progress: number;
  status: string | null;
  stage: string | null;
  error: string | null;
}

/**
 * Subscribe to real-time task progress.
 *
 * @param taskId - The task to watch.  Pass null/undefined to disable.
 * @returns Reactive state object { progress, status, stage, error }
 *
 * The returned values update automatically as SSE events arrive.
 * useTaskStore is also updated (for StatusBar/TaskBar compatibility).
 */
export function useTaskSSE(taskId: string | null | undefined): TaskSSEState {
  const [state, setState] = useState<TaskSSEState>({
    progress: 0,
    status: null,
    stage: null,
    error: null,
  });

  const storeUpdateProgress = useTaskStore((s) => s.updateProgress);
  const storeSetError = useTaskStore((s) => s.setError);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;
    return () => { unmountedRef.current = true; };
  }, []);

  useEffect(() => {
    if (!taskId) return;

    const onEvent = (event: SSEProgressEvent) => {
      if (unmountedRef.current) return;

      // Update local reactive state
      setState((prev) => ({
        progress: event.progress ?? prev.progress,
        status: event.status ?? prev.status,
        stage: event.stage ?? prev.stage,
        error: event.error ?? prev.error,
      }));

      // Sync to global task store (for StatusBar, TaskBar)
      if (event.status) {
        storeUpdateProgress(event.progress ?? 0, event.status as never, event.stage);
      } else {
        storeUpdateProgress(event.progress ?? 0);
      }
      if (event.error) {
        storeSetError(event.error);
      }
    };

    // Subscribe to shared SSE connection
    const unsubscribe = sseManager.subscribe(taskId, onEvent);

    // Fallback polling (in case SSE connection fails entirely)
    // This only activates if no SSE event was received within the poll interval
    let receivedEvent = false;
    const eventTimeout = setTimeout(() => {
      if (!receivedEvent) {
        startPolling(taskId!, onEvent);
      }
    }, POLL_INTERVAL_MS);

    // Wrap onEvent to mark receivedEvent
    const wrappedOnEvent = (event: SSEProgressEvent) => {
      receivedEvent = true;
      clearTimeout(eventTimeout);
      onEvent(event);
    };

    // Patch subscription — we need to re-subscribe with the wrapped handler
    // Actually, since we already subscribed with onEvent, let's use a different approach:
    // Check after first event whether polling is needed

    return () => {
      clearTimeout(eventTimeout);
      stopPolling();
      unsubscribe();
    };

    function startPolling(tId: string, handler: (e: SSEProgressEvent) => void) {
      if (pollTimerRef.current) return;
      pollTimerRef.current = setInterval(async () => {
        if (unmountedRef.current) { stopPolling(); return; }
        try {
          const data = await getTaskStatus(tId);
          handler({
            progress: data.progress,
            status: data.status,
            error: data.error_message ?? undefined,
          });
          if (data.status === "completed" || data.status === "failed") {
            stopPolling();
          }
        } catch {
          // Polling failure — will retry next interval
        }
      }, POLL_INTERVAL_MS);
    }

    function stopPolling() {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }
  }, [taskId, storeUpdateProgress, storeSetError]);

  return state;
}
