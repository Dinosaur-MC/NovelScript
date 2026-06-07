import { describe, it, expect, beforeEach } from "vitest";
import { useTaskStore } from "../../stores/task-store";

function reset() {
  useTaskStore.setState({
    taskId: null,
    scriptId: null,
    novelId: null,
    status: null,
    progress: 0,
    errorMessage: null,
  });
}

beforeEach(reset);

describe("task-store", () => {
  it("setTask sets taskId, novelId, status, progress and clears error", () => {
    // pre-seed an error
    useTaskStore.getState().setError("old error");
    expect(useTaskStore.getState().errorMessage).toBe("old error");

    useTaskStore.getState().setTask("t1", "n1", null, "converting", 42);

    const s = useTaskStore.getState();
    expect(s.taskId).toBe("t1");
    expect(s.novelId).toBe("n1");
    expect(s.status).toBe("converting");
    expect(s.progress).toBe(42);
    expect(s.errorMessage).toBeNull();
  });

  it("setTask defaults progress to 0", () => {
    useTaskStore.getState().setTask("t2", "n2", null, "pending");
    expect(useTaskStore.getState().progress).toBe(0);
  });

  it("updateProgress updates progress and optionally status", () => {
    useTaskStore.getState().setTask("t", "n", null, "converting", 10);
    useTaskStore.getState().updateProgress(35);
    expect(useTaskStore.getState().progress).toBe(35);
    // Status unchanged when not provided
    expect(useTaskStore.getState().status).toBe("converting");

    useTaskStore.getState().updateProgress(80, "completed");
    expect(useTaskStore.getState().progress).toBe(80);
    expect(useTaskStore.getState().status).toBe("completed");
  });

  it("setError sets status to failed and records message", () => {
    useTaskStore.getState().setTask("t", "n", null, "converting", 50);
    useTaskStore.getState().setError("something went wrong");
    expect(useTaskStore.getState().status).toBe("failed");
    expect(useTaskStore.getState().errorMessage).toBe("something went wrong");
  });

  it("clearTask resets to initial state", () => {
    useTaskStore.getState().setTask("t", "n", null, "completed", 100);
    useTaskStore.getState().clearTask();
    expect(useTaskStore.getState().taskId).toBeNull();
    expect(useTaskStore.getState().novelId).toBeNull();
    expect(useTaskStore.getState().status).toBeNull();
    expect(useTaskStore.getState().progress).toBe(0);
    expect(useTaskStore.getState().errorMessage).toBeNull();
  });
});
