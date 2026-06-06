import { create } from "zustand";

export type TaskStatusValue =
  | "pending"
  | "preprocessing"
  | "converting"
  | "completed"
  | "failed";

interface TaskState {
  taskId: string | null;
  novelId: string | null;
  status: TaskStatusValue | null;
  progress: number; // 0–100
  stage: string | null; // e.g. "chunking", "graphrag", "converting"
  errorMessage: string | null;

  setTask: (taskId: string, novelId: string, status: TaskStatusValue, progress?: number) => void;
  updateProgress: (progress: number, status?: TaskStatusValue, stage?: string) => void;
  setError: (error: string) => void;
  clearTask: () => void;
}

const INITIAL: Pick<TaskState, "taskId" | "novelId" | "status" | "progress" | "stage" | "errorMessage"> = {
  taskId: null,
  novelId: null,
  status: null,
  progress: 0,
  stage: null,
  errorMessage: null,
};

export const useTaskStore = create<TaskState>((set) => ({
  ...INITIAL,

  setTask: (taskId, novelId, status, progress = 0) =>
    set({ taskId, novelId, status, progress, stage: null, errorMessage: null }),

  updateProgress: (progress, status, stage) =>
    set((s) => ({
      progress,
      ...(status ? { status } : {}),
      ...(stage !== undefined ? { stage } : {}),
      ...(s.status === "failed" ? { errorMessage: null } : {}),
    })),

  setError: (error) => set({ status: "failed", stage: null, errorMessage: error }),

  clearTask: () => set({ ...INITIAL }),
}));
