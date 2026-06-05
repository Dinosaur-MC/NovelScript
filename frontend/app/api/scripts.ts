import { request } from "./client";

export interface ScriptLight {
  script_id: string;
  novel_id: string;
  status: string;
  progress: number;
  summary: string | null;
  scene_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScriptFull {
  script_id: string;
  novel_id: string;
  status: string;
  progress: number;
  summary: string | null;
  script_yaml: string | null;
  script_json: Record<string, unknown> | null;
  script_fountain: string | null;
  characters_json: Record<string, unknown>[] | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScriptUpdateResult {
  script_id: string;
  updated_at: string;
  validation: { valid: boolean; errors: string | null };
}

export function listScripts(novelId?: string, status?: string, page = 1, limit = 20) {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (novelId) params.set("novel_id", novelId);
  if (status) params.set("status", status);
  return request<{ items: ScriptLight[]; total: number; page: number; limit: number }>(
    `/scripts/?${params}`,
  );
}

export function getScript(id: string) {
  return request<ScriptFull>(`/scripts/${id}`);
}

export function updateScript(id: string, scriptYaml: string) {
  return request<ScriptUpdateResult>(`/scripts/${id}`, {
    method: "PUT",
    body: JSON.stringify({ script_yaml: scriptYaml }),
  });
}

export function deleteScript(id: string) {
  return request<{ script_id: string }>(`/scripts/${id}`, { method: "DELETE" });
}

export function exportScript(
  id: string,
  format: "yaml" | "json" | "fountain",
): Promise<string> {
  return request<string>(`/scripts/${id}/export?format=${format}`);
}
