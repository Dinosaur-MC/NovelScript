/**
 * Centralized SSE connection manager for task progress streaming.
 *
 * Problem: Multiple components may display task status simultaneously
 * (novel page, dashboard, status bar), but each should NOT open its
 * own EventSource connection.
 *
 * Solution: Singleton SSEManager that maintains ONE EventSource per
 * task_id, with reference counting.  Components subscribe via a hook;
 * when the last subscriber unsubscribes the connection is closed.
 *
 * Usage (via useTaskSSE hook):
 *   const { progress, status, stage, error } = useTaskSSE(taskId);
 *   // → reactive values updated from the shared SSE stream
 */

type SSEEventCallback = (event: SSEProgressEvent) => void;

export interface SSEProgressEvent {
  progress: number;
  status?: string;
  stage?: string;
  script_id?: string;
  error?: string;
}

interface ConnectionState {
  es: EventSource;
  refCount: number;
  subscribers: Set<SSEEventCallback>;
}

class SSEManager {
  private connections = new Map<string, ConnectionState>();
  private baseUrl: string;

  constructor() {
    this.baseUrl = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  }

  /**
   * Subscribe to task progress events.
   * Creates a shared EventSource if one doesn't exist for this taskId.
   * Returns an unsubscribe function.
   */
  subscribe(taskId: string, callback: SSEEventCallback): () => void {
    let state = this.connections.get(taskId);

    if (!state) {
      state = this.createConnection(taskId);
      this.connections.set(taskId, state);
    }

    state.refCount++;
    state.subscribers.add(callback);

    // Return unsubscribe function
    return () => {
      const s = this.connections.get(taskId);
      if (!s) return;

      s.subscribers.delete(callback);
      s.refCount--;

      if (s.refCount <= 0) {
        s.es.close();
        this.connections.delete(taskId);
      }
    };
  }

  /**
   * Check if any subscriber is listening for a task.
   */
  hasSubscribers(taskId: string): boolean {
    const state = this.connections.get(taskId);
    return state !== undefined && state.refCount > 0;
  }

  /**
   * Close all connections (used on app unmount / logout).
   */
  closeAll(): void {
    for (const [, state] of this.connections) {
      state.es.close();
    }
    this.connections.clear();
  }

  private createConnection(taskId: string): ConnectionState {
    const url = `${this.baseUrl}/tasks/${taskId}/stream`;
    const es = new EventSource(url);

    const subscribers = new Set<SSEEventCallback>();
    const state: ConnectionState = { es, refCount: 0, subscribers };

    // ── progress ──────────────────────────────────────────────
    es.addEventListener("progress", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEProgressEvent;
        this.broadcast(taskId, data);
      } catch { /* malformed */ }
    });

    // ── complete ──────────────────────────────────────────────
    es.addEventListener("complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEProgressEvent;
        data.status = "completed";
        this.broadcast(taskId, data);
      } catch {
        this.broadcast(taskId, { progress: 100, status: "completed" });
      }
      // Close on terminal event — subscribers that arrive later will
      // get terminal state from polling or reconnect.
      state.es.close();
    });

    // ── error (server-sent error event) ───────────────────────
    es.addEventListener("error", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        this.broadcast(taskId, { progress: 0, status: "failed", error: data.error ?? "Pipeline failed" });
      } catch { /* ignore */ }
      es.close();
    });

    // ── onerror (connection failure) ─────────────────────────
    es.onerror = () => {
      // Connection dropped — EventSource auto-reconnects.
      // Only act if the browser gave up (readyState === CLOSED).
      if (es.readyState === EventSource.CLOSED) {
        this.connections.delete(taskId);
      }
    };

    return state;
  }

  private broadcast(taskId: string, event: SSEProgressEvent): void {
    const state = this.connections.get(taskId);
    if (!state) return;
    for (const cb of state.subscribers) {
      try {
        cb(event);
      } catch {
        /* subscriber error — don't break the broadcast */
      }
    }
  }
}

// ── Singleton ────────────────────────────────────────────────────────
export const sseManager = new SSEManager();

// Make singleton globally accessible for debug
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__sseManager = sseManager;
}
