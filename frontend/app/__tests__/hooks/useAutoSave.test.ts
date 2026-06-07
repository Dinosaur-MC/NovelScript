import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAutoSave } from "../../hooks/useAutoSave";
import { useScriptStore } from "../../stores/script-store";
import { useEditorStore } from "../../stores/editor-store";

vi.mock("../../api/scripts", () => ({
  updateScript: vi.fn(),
}));

import { updateScript } from "../../api/scripts";

const mockUpdateScript = vi.mocked(updateScript);

beforeEach(() => {
  vi.clearAllMocks();
  useScriptStore.setState({
    scriptId: null,
    title: "",
    sourceType: "",
    yaml: null,
    scenes: [],
    characters: [],
    knowledgeGraph: null,
    sourceRefMap: new Map(),
  });
  useEditorStore.getState().setValidationErrors([]);
  useEditorStore.getState().markDirty(false);
});

describe("useAutoSave", () => {
  it("debounces 8s before calling updateScript", async () => {
    vi.useFakeTimers();
    useScriptStore.getState().loadScript({ script_id: "script-1" });

    mockUpdateScript.mockResolvedValueOnce({
      script_id: "script-1",
      updated_at: "2026-06-06T12:00:00Z",
      validation: { valid: true, errors: null },
    });

    const { result } = renderHook(() => useAutoSave());

    act(() => { result.current.triggerSave("scenes:\n  - test"); });
    expect(mockUpdateScript).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(8000));
    expect(mockUpdateScript).toHaveBeenCalledTimes(1);
    expect(mockUpdateScript).toHaveBeenCalledWith("script-1", "scenes:\n  - test");

    vi.useRealTimers();
  });

  it("skips save when scriptId is null", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useAutoSave());
    act(() => result.current.triggerSave("content"));
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(mockUpdateScript).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("cancels pending save when new text arrives (last-write-wins)", async () => {
    vi.useFakeTimers();
    useScriptStore.getState().loadScript({ script_id: "script-2" });

    const { result } = renderHook(() => useAutoSave());

    act(() => result.current.triggerSave("first version"));
    await act(() => vi.advanceTimersByTimeAsync(4000));
    act(() => result.current.triggerSave("second version"));

    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(mockUpdateScript).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(mockUpdateScript).toHaveBeenCalledTimes(1);
    expect(mockUpdateScript).toHaveBeenCalledWith("script-2", "second version");

    vi.useRealTimers();
  });

  it("sets validationErrors on invalid YAML response", async () => {
    vi.useFakeTimers();
    useScriptStore.getState().loadScript({ script_id: "script-3" });

    mockUpdateScript.mockResolvedValueOnce({
      script_id: "script-3",
      updated_at: "2026-06-06T12:00:00Z",
      validation: { valid: false, errors: "mapping values are not allowed here" },
    });

    const { result } = renderHook(() => useAutoSave());
    act(() => result.current.triggerSave("invalid:: yaml"));
    await act(() => vi.advanceTimersByTimeAsync(8000));

    expect(useEditorStore.getState().validationErrors).toEqual([
      "mapping values are not allowed here",
    ]);

    vi.useRealTimers();
  });
});
