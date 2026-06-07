import { request } from "./client";

export interface TaskLight {
  id: string;
  novel_id: string;
  status: string;
  progress: number;
  summary: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskFull {
  id: string;
  novel_id: string;
  user_id: string | null;
  status: string;
  progress: number;
  summary: string | null;
  characters_json: Record<string, unknown>[] | null;
  script_yaml: string | null;
  script_json: Record<string, unknown> | null;
  script_fountain: string | null;
  error_message: string | null;
  pipeline_config: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface KGNode {
  id: string;
  node_type: string;
  name: string;
  aliases: string[];
  description: string | null;
  properties: Record<string, unknown>;
}

export interface KGEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  weight: number;
}

export interface TaskStatus {
  task_id: string;
  status: string;
  progress: number;
  error_message: string | null;
}

export function createTask(novelId: string, pipelineConfig = {}) {
  return request<{ task_id: string; status: string }>("/tasks/", {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, pipeline_config: pipelineConfig }),
  });
}

export function getTask(id: string) {
  return request<TaskFull>(`/tasks/${id}`);
}

export function getTaskStatus(id: string) {
  return request<TaskStatus>(`/tasks/${id}/status`);
}

export function listTasks(novelId?: string, status?: string, page = 1, limit = 20) {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (novelId) params.set("novel_id", novelId);
  if (status) params.set("status", status);
  return request<{ tasks: TaskLight[]; total: number; page: number; limit: number }>(
    `/tasks/?${params}`,
  );
}

export function resumeTask(id: string) {
  return request<{ task_id: string; status: string }>(`/tasks/${id}/resume`, {
    method: "POST",
  });
}

/** Create an EventSource for real-time SSE progress streaming. */
export function createTaskStream(id: string): EventSource {
  const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  return new EventSource(`${BASE_URL}/tasks/${id}/stream`);
}
