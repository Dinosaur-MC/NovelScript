import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSSE } from "../../hooks/useSSE";
import { useTaskStore } from "../../stores/task-store";

// Mock the task status API for polling fallback
vi.mock("../../api/tasks", () => ({
  getTaskStatus: vi.fn(),
  createTaskStream: vi.fn(),
}));

import { getTaskStatus, createTaskStream } from "../../api/tasks";

const mockGetStatus = vi.mocked(getTaskStatus);
const mockCreateStream = vi.mocked(createTaskStream);

function setActiveTask() {
  useTaskStore.setState({
    taskId: "task-1",
    novelId: "novel-1",
    status: "converting",
    progress: 35,
    errorMessage: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useTaskStore.setState({
    taskId: null,
    novelId: null,
    status: null,
    progress: 0,
    errorMessage: null,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSSE", () => {
  describe("active task → SSE primary path", () => {
    it("opens an EventSource and listens for progress events", () => {
      const listeners: Record<string, (e: MessageEvent) => void> = {};
      const mockES = {
        addEventListener: vi.fn((type: string, fn: unknown) => {
          listeners[type] = fn as (e: MessageEvent) => void;
        }),
        close: vi.fn(),
        onerror: null as ((() => void) | null),
      };
      mockCreateStream.mockReturnValue(mockES as unknown as EventSource);
      setActiveTask();

      renderHook(() => useSSE());

      expect(mockCreateStream).toHaveBeenCalledWith("task-1");
      expect(mockES.addEventListener).toHaveBeenCalledWith(
        "progress",
        expect.any(Function),
      );
      expect(mockES.addEventListener).toHaveBeenCalledWith(
        "complete",
        expect.any(Function),
      );
      expect(mockES.addEventListener).toHaveBeenCalledWith(
        "error",
        expect.any(Function),
      );

      // Simulate a progress event
      listeners.progress({
        data: JSON.stringify({ progress: 65, stage: "converting" }),
      } as MessageEvent);
      expect(useTaskStore.getState().progress).toBe(65);
    });

    it("handles complete event and closes the stream", () => {
      const listeners: Record<string, (e: MessageEvent) => void> = {};
      const mockES = {
        addEventListener: vi.fn((type: string, fn: unknown) => {
          listeners[type] = fn as (e: MessageEvent) => void;
        }),
        close: vi.fn(),
        onerror: null,
      };
      mockCreateStream.mockReturnValue(mockES as unknown as EventSource);
      setActiveTask();

      renderHook(() => useSSE());

      listeners.complete({
        data: JSON.stringify({ progress: 100 }),
      } as MessageEvent);
      expect(useTaskStore.getState().status).toBe("completed");
      expect(useTaskStore.getState().progress).toBe(100);
      expect(mockES.close).toHaveBeenCalled();
    });

    it("closes stream on SSE error event", () => {
      const listeners: Record<string, (e: MessageEvent) => void> = {};
      const mockES = {
        addEventListener: vi.fn((type: string, fn: unknown) => {
          listeners[type] = fn as (e: MessageEvent) => void;
        }),
        close: vi.fn(),
        onerror: null,
      };
      mockCreateStream.mockReturnValue(mockES as unknown as EventSource);
      setActiveTask();

      renderHook(() => useSSE());

      listeners.error({
        data: JSON.stringify({ error: "pipeline crashed" }),
      } as MessageEvent);
      expect(mockES.close).toHaveBeenCalled();
    });

    it("falls back to polling on network error", async () => {
      vi.useFakeTimers();
      const mockES = {
        addEventListener: vi.fn(),
        close: vi.fn(),
        onerror: null as ((() => void) | null),
      };
      mockCreateStream.mockReturnValue(mockES as unknown as EventSource);
      mockGetStatus.mockResolvedValue({
        task_id: "task-1",
        status: "converting",
        progress: 50,
        error_message: null,
      });
      setActiveTask();

      const { unmount } = renderHook(() => useSSE());

      // Simulate network error
      mockES.onerror!();

      // Polling should kick in after the error
      await vi.advanceTimersByTimeAsync(3001);
      expect(mockGetStatus).toHaveBeenCalled();
      expect(useTaskStore.getState().progress).toBe(50);

      unmount();
    });
  });

  describe("inactive task", () => {
    it("does nothing when taskId is null", () => {
      renderHook(() => useSSE());
      expect(mockCreateStream).not.toHaveBeenCalled();
    });

    it("does nothing when status is completed", () => {
      useTaskStore.setState({
        taskId: "task-1",
        novelId: "novel-1",
        status: "completed",
        progress: 100,
        errorMessage: null,
      });
      renderHook(() => useSSE());
      expect(mockCreateStream).not.toHaveBeenCalled();
    });

    it("cleans up on unmount", () => {
      const mockES = {
        addEventListener: vi.fn(),
        close: vi.fn(),
        onerror: null,
      };
      mockCreateStream.mockReturnValue(mockES as unknown as EventSource);
      setActiveTask();

      const { unmount } = renderHook(() => useSSE());
      unmount();
      expect(mockES.close).toHaveBeenCalled();
    });
  });
});
