import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoSave } from "../../hooks/useAutoSave";
import { useTaskStore } from "../../stores/task-store";
import { useEditorStore } from "../../stores/editor-store";

vi.mock("../../api/scripts", () => ({
  updateScript: vi.fn(),
}));

import { updateScript } from "../../api/scripts";

const mockUpdateScript = vi.mocked(updateScript);

beforeEach(() => {
  vi.clearAllMocks();
  useTaskStore.setState({
    taskId: null,
    novelId: null,
    status: null,
    progress: 0,
    errorMessage: null,
  });
  useEditorStore.getState().setValidationErrors([]);
});

describe("useAutoSave", () => {
  it("debounces 2s before calling updateScript", async () => {
    vi.useFakeTimers();
    useTaskStore.getState().setTask("task-1", "novel-1", "completed", 100);

    mockUpdateScript.mockResolvedValueOnce({
      script_id: "task-1",
      updated_at: "2026-06-06T12:00:00Z",
      validation: { valid: true, errors: null },
    });

    const { result } = renderHook(() => useAutoSave());

    act(() => {
      result.current.triggerSave("scenes:\n  - test");
    });
    expect(mockUpdateScript).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(mockUpdateScript).toHaveBeenCalledTimes(1);
    expect(mockUpdateScript).toHaveBeenCalledWith("task-1", "scenes:\n  - test");

    vi.useRealTimers();
  });

  it("skips save when taskId is null", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useAutoSave());
    act(() => result.current.triggerSave("content"));
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(mockUpdateScript).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("cancels pending save when new text arrives (last-write-wins)", async () => {
    vi.useFakeTimers();
    useTaskStore.getState().setTask("task-1", "novel-1", "completed", 100);

    const { result } = renderHook(() => useAutoSave());

    act(() => result.current.triggerSave("first version"));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    act(() => result.current.triggerSave("second version"));

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mockUpdateScript).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mockUpdateScript).toHaveBeenCalledTimes(1);
    expect(mockUpdateScript).toHaveBeenCalledWith("task-1", "second version");

    vi.useRealTimers();
  });

  it("sets validationErrors on invalid YAML response", async () => {
    vi.useFakeTimers();
    useTaskStore.getState().setTask("task-2", "novel-2", "completed", 100);

    mockUpdateScript.mockResolvedValueOnce({
      script_id: "task-2",
      updated_at: "2026-06-06T12:00:00Z",
      validation: { valid: false, errors: "mapping values are not allowed here" },
    });

    const { result } = renderHook(() => useAutoSave());
    act(() => result.current.triggerSave("invalid:: yaml"));
    await act(() => vi.advanceTimersByTimeAsync(2000));

    expect(useEditorStore.getState().validationErrors).toEqual([
      "mapping values are not allowed here",
    ]);

    vi.useRealTimers();
  });
});
